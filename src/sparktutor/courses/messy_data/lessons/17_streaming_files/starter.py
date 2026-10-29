"""
Streaming Files - Exercise

An incremental counter over an inbox folder. Files arrive one day at a time;
each run processes only what is new, the counts survive restarts through the
checkpoint, and a foreachBatch ledger records what every micro-batch read in a
way that stays correct when Spark replays a batch.
"""

import json
import os
import shutil
import tempfile

from pyspark.sql import SparkSession, functions as F

EVENTS = "data/messy/events"

# The drift-absorbing schema from "JSON Drift and Quarantine"
EVENT_SCHEMA = """
    event STRING, event_type STRING, user_id BIGINT,
    user STRUCT<id: BIGINT, plan: STRING, geo: STRUCT<country: STRING>>,
    amount STRING,
    items ARRAY<STRUCT<sku: STRING, qty: INT>>,
    ts TIMESTAMP,
    _corrupt STRING
"""


def read_inbox(spark, inbox):
    """A streaming DataFrame over the JSON files in `inbox`, one file per micro-batch.

    Columns: every EVENT_SCHEMA column, plus `file` (the file name) and
    `kind` (event_type, or the old name event).
    """
    # TODO: spark.readStream with EVENT_SCHEMA, the corrupt record column and
    #       one file per micro-batch; add `file` and `kind`
    return None


def run_counter(spark, inbox, checkpoint):
    """Count parsed events per kind over everything that ever arrived.

    Writes to the memory sink `event_counts` in complete mode, processes what
    is available now, waits, and returns numInputRows of each micro-batch.
    """
    # TODO: count parsed events per kind, write them to the memory sink
    #       "event_counts" in complete mode with the checkpoint and availableNow,
    #       wait for the query, return [numInputRows of each progress report]
    return None


def write_ledger(batch_df, batch_id, ledger):
    """One row per file in this micro-batch: file, rows, bad (corrupt) rows.

    Overwrites ledger/batch_id=<id>, so running the same batch again
    replaces its rows instead of adding a second copy.
    """
    # TODO: group by file (rows, bad, latest_ts) and overwrite
    #       ledger/batch_id=<batch_id> as Parquet
    pass


def run_ledger(spark, inbox, checkpoint, ledger):
    """Stream the inbox through write_ledger with foreachBatch; return the query."""
    # TODO: foreachBatch calling write_ledger(df, batch_id, ledger), with the
    #       checkpoint and availableNow; wait and return the query
    return None


# ---- Test harness ----
def deliver(name, inbox):
    """Copy a sample file into the inbox the safe way: hidden name first, then rename."""
    hidden = os.path.join(inbox, "." + name + ".tmp")
    shutil.copy(os.path.join(EVENTS, name), hidden)
    os.rename(hidden, os.path.join(inbox, name))


def expected_counts(names):
    """Parsed events per kind in the given files, counted with Python's json."""
    counts, bad = {}, 0
    for name in names:
        for line in open(os.path.join(EVENTS, name)):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            kind = rec.get("event_type") or rec.get("event")
            counts[kind] = counts.get(kind, 0) + 1
    return counts, bad


def memory_counts(spark):
    return {r["kind"]: r["count"] for r in spark.table("event_counts").collect()}


if __name__ == "__main__":
    spark = (SparkSession.builder
             .appName("StreamingFiles")
             .master("local[*]")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.shuffle.partitions", "4")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    work = tempfile.mkdtemp(prefix="stream_")
    inbox = os.path.join(work, "inbox")
    os.makedirs(inbox)
    counter_ckpt = os.path.join(work, "checkpoints", "counter")
    ledger_ckpt = os.path.join(work, "checkpoints", "ledger")
    ledger = os.path.join(work, "ledger")
    days = sorted(os.listdir(EVENTS))

    try:
        probe = read_inbox(spark, inbox)
        assert probe is not None, "read_inbox() returned None"
        assert probe.isStreaming, "read_inbox should use spark.readStream"
        for col in ("file", "kind", "_corrupt", "ts"):
            assert col in probe.columns, f"read_inbox is missing the column {col}: got {probe.columns}"

        # Day 1 arrives
        deliver(days[0], inbox)
        batches = run_counter(spark, inbox, counter_ckpt)
        assert batches is not None, "run_counter() returned None"
        assert spark.catalog.tableExists("event_counts"), (
            "No table event_counts: write to the memory sink with queryName('event_counts')")
        want, _ = expected_counts(days[:1])
        assert batches == [20], f"Run 1 should process one batch of 20 rows, got {batches}"
        assert memory_counts(spark) == want, f"After day 1 expected {want}, got {memory_counts(spark)}"
        run_ledger(spark, inbox, ledger_ckpt, ledger)

        # Day 2 arrives: only it is read, but the counts include day 1 (state from the checkpoint)
        deliver(days[1], inbox)
        batches = run_counter(spark, inbox, counter_ckpt)
        want, _ = expected_counts(days[:2])
        assert batches == [20], (
            f"Run 2 should read only the new file (one batch of 20 rows), got {batches}. "
            "Reuse the same checkpoint location on every run")
        assert memory_counts(spark) == want, (
            f"After day 2 the counts should cover both days, {want}; got {memory_counts(spark)}. "
            "Use outputMode('complete') so the aggregation state comes back from the checkpoint")
        run_ledger(spark, inbox, ledger_ckpt, ledger)

        # Nothing new: no rows are read
        batches = run_counter(spark, inbox, counter_ckpt)
        assert sum(batches) == 0, f"With no new files nothing should be read, got batches {batches}"

        # Day 3 arrives, with a truncated line at the end
        deliver(days[2], inbox)
        batches = run_counter(spark, inbox, counter_ckpt)
        want, bad = expected_counts(days)
        assert batches == [21], f"Run 4 should read day 3 only (21 lines), got {batches}"
        assert memory_counts(spark) == want, (
            f"After day 3 expected {want} (the truncated line is not counted), got {memory_counts(spark)}")
        run_ledger(spark, inbox, ledger_ckpt, ledger)

        assert os.path.isdir(ledger) and any(n.startswith("batch_id=") for n in os.listdir(ledger)), (
            "The ledger folder is empty: write_ledger should write ledger/batch_id=<batch_id> "
            "and run_ledger should call it through foreachBatch")
        rows = sorted((r["batch_id"], r["file"], r["rows"], r["bad"])
                      for r in spark.read.parquet(ledger).collect())
        expected_ledger = [(0, days[0], 20, 0), (1, days[1], 20, 0), (2, days[2], 21, bad)]
        assert rows == expected_ledger, (
            f"Ledger should be {expected_ledger}, got {rows}. write_ledger writes one row per file "
            "to ledger/batch_id=<batch_id> with mode('overwrite')")

        # Pretend the last run crashed after writing but before committing:
        # remove its commit file (and the checksum the local file system keeps
        # next to it), and Spark replays batch 2 on the next start.
        for name in ("2", ".2.crc"):
            os.remove(os.path.join(ledger_ckpt, "commits", name))
        replay = run_ledger(spark, inbox, ledger_ckpt, ledger)
        assert replay is not None, "run_ledger() should return the finished query"
        replayed = [(p.batchId, p.numInputRows) for p in replay.recentProgress if p.numInputRows]
        assert replayed == [(2, 21)], f"Spark should replay batch 2 with 21 rows, got {replayed}"
        again = sorted((r["batch_id"], r["file"], r["rows"], r["bad"])
                       for r in spark.read.parquet(ledger).collect())
        assert again == expected_ledger, (
            f"After the replay the ledger should be unchanged, got {again}. Overwrite the batch's "
            "folder instead of appending, so a replayed batch replaces its own rows")

        print("Counts after three days:")
        spark.table("event_counts").orderBy("kind").show()
        print("Ledger:")
        spark.read.parquet(ledger).orderBy("batch_id").show(truncate=False)
        print("Checkpoint folders:", sorted(os.listdir(counter_ckpt)))
        print("All tests passed!")
    finally:
        for q in spark.streams.active:
            q.stop()
        spark.stop()
