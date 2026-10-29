"""
Streaming Internals: Checkpoints, State and Real-Time Mode - Solution

A stateful sessionizer over the checkout service's event drops
(data/messy/checkout_events/drop_1.jsonl to drop_4.jsonl), built with the
row-based transformWithState API (4.1) on the RocksDB state store, and
proved from the outside:

- checkpoint_status() reads offsets/ and commits/ with plain Python and
  says which batch the next run will execute (and whether it is a replay);
- Sessionizer keeps one ValueState and one MapState per user, drops
  re-sent events by event_id, closes a session on a gap of more than 30
  minutes (in handleInputRows) or when its event-time timer fires
  (in handleExpiredTimer);
- write_batch() is a foreachBatch sink that stays exactly-once when Spark
  replays a batch after a crash;
- open_sessions() reads the live state back with the state data source.

The harness runs the query three times on one checkpoint: drops 1 and 2,
then drops 3 and 4 with a crash injected after the sink wrote batch 4, then
a restart that replays batch 4. The final output must match a reference
sessionization computed in plain Python.
"""

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone

from pyspark.sql import Row, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.streaming import StatefulProcessor

GAP_MS = 30 * 60 * 1000          # a gap longer than this ends a session
WATERMARK = "10 minutes"
EVENT_SCHEMA = ("event_id STRING, user STRING, action STRING, page STRING, "
                "ts TIMESTAMP, amount DOUBLE")
OUTPUT_SCHEMA = ("user STRING, start_ms LONG, end_ms LONG, clicks INT, "
                 "revenue DOUBLE, closed_by STRING")
ROCKSDB = "org.apache.spark.sql.execution.streaming.state.RocksDBStateStoreProvider"


# ---- 1. Reading a checkpoint without Spark ----
def _batch_files(folder):
    """Batch ids of the visible log files in offsets/ or commits/."""
    if not os.path.isdir(folder):
        return []
    return sorted(int(n) for n in os.listdir(folder) if n.isdigit())


def checkpoint_status(checkpoint):
    """Summarise a checkpoint the way MicroBatchExecution does on restart.

    Returns a dict with:
      latest_offset  highest batch id in offsets/ (None if empty)
      latest_commit  highest batch id in commits/ (None if empty)
      will_replay    True if the newest planned batch was never committed
      next_batch     the batch id the next run will execute
      watermark_ms   batchWatermarkMs recorded in the newest offsets file
    """
    offsets = _batch_files(os.path.join(checkpoint, "offsets"))
    commits = _batch_files(os.path.join(checkpoint, "commits"))
    latest_offset = offsets[-1] if offsets else None
    latest_commit = commits[-1] if commits else None
    watermark_ms = None
    if latest_offset is not None:
        with open(os.path.join(checkpoint, "offsets", str(latest_offset))) as f:
            lines = f.read().splitlines()
        assert lines[0] == "v1", f"unexpected offset log version {lines[0]!r}"
        watermark_ms = json.loads(lines[1])["batchWatermarkMs"]
    will_replay = latest_offset is not None and latest_offset != latest_commit
    if latest_offset is None:
        next_batch = 0
    elif will_replay:
        next_batch = latest_offset
    else:
        next_batch = latest_offset + 1
    return {"latest_offset": latest_offset, "latest_commit": latest_commit,
            "will_replay": will_replay, "next_batch": next_batch,
            "watermark_ms": watermark_ms}


# ---- 2. The stateful processor ----
def to_ms(ts):
    """Input timestamps arrive as timezone-aware datetimes; keep epoch ms."""
    return int(ts.timestamp() * 1000)


class Sessionizer(StatefulProcessor):
    def init(self, handle):
        self.handle = handle
        # Times are stored as epoch milliseconds (LONG), never as TIMESTAMP:
        # a TIMESTAMP read back from state is a naive datetime in the
        # worker's local time zone.
        self.session = handle.getValueState(
            "session", "start_ms LONG, last_ms LONG, clicks INT, revenue DOUBLE")
        self.seen = handle.getMapState("seen", "event_id STRING", "ts_ms LONG")

    def _closed(self, user, s, how):
        return Row(user=user, start_ms=s[0], end_ms=s[1], clicks=s[2],
                   revenue=round(s[3], 2), closed_by=how)

    def handleInputRows(self, key, rows, timerValues):
        user = key[0]
        s = self.session.get() if self.session.exists() else None
        for r in sorted(rows, key=lambda r: r.ts):
            if self.seen.containsKey((r.event_id,)):
                continue                                  # re-sent event
            ms = to_ms(r.ts)
            if s is not None and ms > s[1] + GAP_MS:
                yield self._closed(user, s, "gap")        # the old session ended
                self.seen.clear()
                s = None
            amount = r.amount or 0.0
            if s is None:
                s = (ms, ms, 1, amount)
            else:
                s = (min(s[0], ms), max(s[1], ms), s[2] + 1, s[3] + amount)
            self.seen.updateValue((r.event_id,), (ms,))
        if s is None:
            return                                         # only duplicates arrived
        for t in self.handle.listTimers():
            self.handle.deleteTimer(t)
        self.session.update(s)
        self.handle.registerTimer(s[1] + GAP_MS)

    def handleExpiredTimer(self, key, timerValues, expiredTimerInfo):
        s = self.session.get()
        self.session.clear()
        self.seen.clear()
        yield self._closed(key[0], s, "timer")

    def close(self):
        pass


# ---- 3. An exactly-once foreachBatch sink ----
def write_batch(df, batch_id, out_dir):
    """Write one micro-batch so that a replay of batch_id replaces it."""
    (df.write.mode("overwrite")
       .parquet(os.path.join(out_dir, f"batch_id={batch_id}")))


# ---- 4. Reading live state ----
def open_sessions(spark, checkpoint):
    """Open sessions from the checkpoint: one row per user with the
    session fields and the registered timer."""
    sessions = (spark.read.format("statestore")
                .option("stateVarName", "session").load(checkpoint)
                .select(F.col("key.user").alias("user"), "value.*"))
    timers = (spark.read.format("statestore")
              .option("readRegisteredTimers", "true").load(checkpoint)
              .select(F.col("key.user").alias("user"),
                      F.col("expiration_timestamp_ms").alias("timer_ms")))
    return sessions.join(timers, "user", "left")


# ---- Harness (given) ----
CRASH = {"batch": None}


def run_query(spark, inbox, checkpoint, out_dir):
    """One availableNow run over the inbox; returns the batch ids it ran."""
    def sink(df, batch_id):
        write_batch(df, batch_id, out_dir)
        if CRASH["batch"] == batch_id:
            CRASH["batch"] = None
            raise RuntimeError(f"injected crash after the sink wrote batch {batch_id}")

    events = (spark.readStream.schema(EVENT_SCHEMA)
              .option("maxFilesPerTrigger", 1).json(inbox))
    q = (events.withWatermark("ts", WATERMARK).groupBy("user")
         .transformWithState(Sessionizer(), OUTPUT_SCHEMA, "Append", "EventTime")
         .writeStream.foreachBatch(sink)
         .option("checkpointLocation", checkpoint)
         .trigger(availableNow=True).start())
    try:
        q.awaitTermination()
    except Exception as e:  # noqa: BLE001 - the injected crash surfaces here
        if "injected crash" not in str(e):
            raise
        print(f"  the query stopped: injected crash after the sink wrote a batch")
    return [p.batchId for p in q.recentProgress]


def parse_ms(s):
    return int(datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
               .replace(tzinfo=timezone.utc).timestamp() * 1000)


def reference(drops, delay_ms=10 * 60 * 1000):
    """Plain-Python sessionization with the same rules, for checking.

    Each drop is one micro-batch. An event is dropped as late when its time
    is at or before the watermark of the batch it arrives in (the newest
    event time of the earlier batches minus the delay). Re-sent events
    (same event_id) count once.
    """
    seen, events, max_ts, watermark = set(), [], None, None
    for rows in drops:
        for e in rows:
            ms = parse_ms(e["ts"])
            if watermark is not None and ms <= watermark:
                continue
            if e["event_id"] in seen:
                continue
            seen.add(e["event_id"])
            events.append((e["user"], ms, e.get("amount") or 0.0))
        batch_max = max(parse_ms(e["ts"]) for e in rows)
        max_ts = batch_max if max_ts is None else max(max_ts, batch_max)
        watermark = max_ts - delay_ms
    sessions = []
    for user in sorted({u for u, _, _ in events}):
        cur = None
        for _, ms, amt in sorted(e for e in events if e[0] == user):
            if cur and ms > cur[2] + GAP_MS:
                sessions.append(cur)
                cur = None
            cur = [user, ms, ms, 1, amt] if cur is None else \
                [user, cur[1], ms, cur[3] + 1, cur[4] + amt]
        sessions.append(cur)
    closed = [s for s in sessions if s[2] + GAP_MS <= watermark or
              any(o[0] == s[0] and o[1] > s[2] for o in sessions)]
    open_ = [s for s in sessions if s not in closed]
    as_tuples = lambda xs: sorted((u, a, b, n, round(r, 2)) for u, a, b, n, r in xs)
    return as_tuples(closed), as_tuples(open_), watermark


def read_drop(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    spark = (SparkSession.builder.master("local[2]")
             .appName("streaming_internals")
             .config("spark.sql.shuffle.partitions", "2")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.streaming.stateStore.providerClass", ROCKSDB)
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    src = "data/messy/checkout_events"
    drops = [read_drop(f"{src}/drop_{i}.jsonl") for i in range(1, 5)]
    work = tempfile.mkdtemp(prefix="streaming_internals_")
    inbox, ck, out = (os.path.join(work, d) for d in ("inbox", "checkpoint", "out"))
    os.makedirs(inbox)

    def drop(i):
        target = os.path.join(inbox, f"drop_{i}.jsonl")
        shutil.copy(f"{src}/drop_{i}.jsonl", target)
        os.utime(target, (1_000_000 + i, 1_000_000 + i))  # file order = drop order

    # --- Test 1: checkpoint_status on hand-made checkpoints ---
    print("Test 1: checkpoint_status() on hand-made checkpoints")
    fake = os.path.join(work, "fake")
    for d in ("offsets", "commits"):
        os.makedirs(os.path.join(fake, d))
    empty = checkpoint_status(fake)
    assert empty is not None, "checkpoint_status() returned None. Return a dict."
    assert empty["next_batch"] == 0 and empty["latest_offset"] is None, (
        f"An empty checkpoint starts at batch 0 with no offsets, got {empty}")
    meta = json.dumps({"batchWatermarkMs": 1791194548000, "batchTimestampMs": 1, "conf": {}})
    for b in range(3):
        with open(os.path.join(fake, "offsets", str(b)), "w") as f:
            f.write(f"v1\n{meta}\n{{\"logOffset\":{b}}}")
        with open(os.path.join(fake, "offsets", f".{b}.crc"), "w") as f:
            f.write("crc")
    for b in range(2):
        with open(os.path.join(fake, "commits", str(b)), "w") as f:
            f.write('v1\n{"nextBatchWatermarkMs":0}')
    st = checkpoint_status(fake)
    assert st["latest_offset"] == 2 and st["latest_commit"] == 1, (
        f"offsets/ holds batches 0 to 2 and commits/ holds 0 to 1 (ignore .crc files), got {st}")
    assert st["will_replay"] is True and st["next_batch"] == 2, (
        "offsets/2 exists without commits/2, so the next run replays batch 2. "
        f"Got will_replay={st['will_replay']}, next_batch={st['next_batch']}")
    assert st["watermark_ms"] == 1791194548000, (
        "watermark_ms is batchWatermarkMs from the JSON on the second line of the "
        f"newest offsets file, got {st['watermark_ms']}")
    with open(os.path.join(fake, "commits", "2"), "w") as f:
        f.write('v1\n{"nextBatchWatermarkMs":0}')
    st = checkpoint_status(fake)
    assert st["will_replay"] is False and st["next_batch"] == 3, (
        f"With commits/2 present the next run starts batch 3, got {st}")
    print("  ok")

    expected_closed, expected_open, final_wm = reference(drops)
    exp_closed_12, exp_open_12, wm_12 = reference(drops[:2])

    # --- Test 2: first run (drops 1 and 2) and the state it leaves ---
    print("Test 2: first run over drops 1 and 2, then read the state")
    drop(1)
    drop(2)
    try:
        batches = run_query(spark, inbox, ck, out)
    except Exception as e:  # noqa: BLE001
        raise AssertionError(
            "The streaming query failed. Check Sessionizer: handleInputRows and "
            "handleExpiredTimer must yield Row objects (or nothing), and the "
            "handleExpiredTimer parameters must be named exactly "
            "(self, key, timerValues, expiredTimerInfo). Spark said:\n"
            + str(e).splitlines()[0][:600]) from None
    print(f"  batches run: {batches}")
    st = checkpoint_status(ck)
    print(f"  checkpoint_status: {st}")
    assert st["will_replay"] is False and st["next_batch"] == 3, (
        "After the first run every planned batch (0, 1 and a no-data batch 2 that "
        f"advanced the watermark) is committed, so the next batch is 3. Got {st}")
    assert st["watermark_ms"] == wm_12, (
        f"The newest offsets file should record watermark {wm_12}, got {st['watermark_ms']}")
    state = open_sessions(spark, ck)
    assert state is not None, "open_sessions() returned None. Return a DataFrame."
    got = sorted((r.user, r.start_ms, r.last_ms, r.clicks, round(r.revenue, 2))
                 for r in state.collect())
    assert got == exp_open_12, (
        "The open sessions read from state do not match the expected ones.\n"
        f"  expected {exp_open_12}\n  got      {got}\n"
        "Did you skip re-sent event_ids and keep the earliest start and latest event?")
    timers = {r.user: r.timer_ms for r in state.collect()}
    assert all(timers[u] == last + GAP_MS for u, _, last, _, _ in exp_open_12), (
        f"Each open session needs exactly one timer at last_ms + GAP_MS, got {timers}")
    state.orderBy("user").show(truncate=False)

    # --- Test 3: crash after the sink wrote batch 4 ---
    print("Test 3: second run over drops 3 and 4 with a crash after the sink wrote batch 4")
    drop(3)
    drop(4)
    CRASH["batch"] = 4
    run_query(spark, inbox, ck, out)
    st = checkpoint_status(ck)
    print(f"  checkpoint_status: {st}")
    assert st["latest_offset"] == 4 and st["latest_commit"] == 3 and st["will_replay"], (
        "After the crash offsets/4 exists but commits/4 does not, so batch 4 "
        f"must be replayed. Got {st}")

    # --- Test 4: restart replays batch 4; the output stays exactly-once ---
    print("Test 4: restart; batch 4 is replayed and the output stays exactly-once")
    batches = run_query(spark, inbox, ck, out)
    print(f"  batches run: {batches}")
    assert batches and batches[0] == 4, f"The restart must begin by replaying batch 4, ran {batches}"
    result = spark.read.parquet(out)
    rows = result.collect()
    got = sorted((r.user, r.start_ms, r.end_ms, r.clicks, round(r.revenue, 2)) for r in rows)
    dupes = len(got) - len(set(got))
    assert dupes == 0, (
        f"{dupes} session(s) appear twice in the output. The replay of batch 4 "
        "appended a second copy. Make write_batch() replace the batch's folder.")
    assert got == expected_closed, (
        "The closed sessions do not match the reference.\n"
        f"  expected {expected_closed}\n  got      {got}")
    by = {r.closed_by for r in rows}
    assert by == {"gap", "timer"}, (
        f"Sessions should be closed both by a new click after a gap and by a timer, got {by}")
    (result.select("user", F.timestamp_millis("start_ms").alias("start"),
                   F.timestamp_millis("end_ms").alias("end"), "clicks", "revenue",
                   "closed_by", "batch_id")
           .orderBy("user", "start").show(truncate=False))
    still_open = sorted((r.user, r.start_ms, r.last_ms, r.clicks, round(r.revenue, 2))
                        for r in open_sessions(spark, ck).collect())
    assert still_open == expected_open, (
        f"Open sessions at the end: expected {expected_open}, got {still_open}")
    print(f"  still open: {[s[0] for s in still_open]}")

    shutil.rmtree(work, ignore_errors=True)
    print("All tests passed!")
    spark.stop()
