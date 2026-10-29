"""
Streaming Messy Data: Drift, Dead Letters and State - Solution

A click tracker uploads JSON Lines files ("drops") into an inbox. Two
streaming queries read the inbox:

  ingest     text lines -> parse_events -> foreachBatch(route_batch)
             valid events to silver/, everything else to dead_letter/,
             both keyed by batch id so a replayed batch is harmless
  sessions   text lines -> parse_events -> watermark -> dedupe -> session
             windows, appended to a Parquet table of finished sessions

The harness feeds the four drops one at a time, restarting both queries
from their checkpoints after each drop, then forces a replay.
"""

import os
import shutil
import tempfile

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

INBOX_SOURCE = "data/messy/clickstream"
KNOWN_KEYS = ["event_id", "user_id", "type", "event_type", "page", "ts"]
CLOCK_SKEW = "5 minutes"


def parse_events(lines: DataFrame, now) -> DataFrame:
    """Parse JSON Lines that may be broken or drifting, never failing.

    `lines` has one string column, `value` (the text source). `now` is a
    timestamp Column: events later than now + CLOCK_SKEW come from a
    device with a wrong clock. Returns the columns
    line, event_id, user_id, type, page, ts, unknown_keys, error.
    """
    v = F.try_parse_json("value")
    parsed = lines.select(
        F.col("value").alias("line"),
        v.alias("v"),
    ).select(
        "line",
        F.try_variant_get("v", "$.event_id", "string").alias("event_id"),
        F.try_variant_get("v", "$.user_id", "string").alias("user_id"),
        # Tracker 2.0 renamed `type` to `event_type`: accept both.
        F.coalesce(F.try_variant_get("v", "$.type", "string"),
                   F.try_variant_get("v", "$.event_type", "string")).alias("type"),
        F.try_variant_get("v", "$.page", "string").alias("page"),
        F.try_to_timestamp(F.try_variant_get("v", "$.ts", "string")).alias("ts"),
        # Keys nobody told us about: the early warning for the next drift.
        F.array_except(F.expr("json_object_keys(line)"),
                       F.array(*[F.lit(k) for k in KNOWN_KEYS])).alias("unknown_keys"),
        F.col("v").isNull().alias("_bad_json"),
    )
    error = (F.when(F.col("_bad_json"), "bad_json")
             .when(F.col("event_id").isNull(), "missing_event_id")
             .when(F.col("user_id").isNull(), "missing_user")
             .when(F.col("ts").isNull(), "bad_ts")
             .when(F.col("ts") > now + F.expr(f"INTERVAL {CLOCK_SKEW}"), "future_ts"))
    return parsed.withColumn("error", error).drop("_bad_json")


def route_batch(batch: DataFrame, batch_id: int, root: str) -> None:
    """foreachBatch body: write one micro-batch so that a replay is harmless.

    - dead letters (error IS NOT NULL): columns line and error, as JSON in
      root/dead_letter/batch_id=<id>
    - valid events: deduplicated on event_id within the batch, minus the
      event_ids already in silver from *other* batches, as Parquet in
      root/silver/batch_id=<id> (columns event_id, user_id, type, page, ts,
      unknown_keys)
    Both use mode("overwrite") on the batch's own folder.
    """
    spark = batch.sparkSession
    batch = batch.persist()          # used twice: compute the batch once
    try:
        (batch.where("error IS NOT NULL").select("line", "error")
         .write.mode("overwrite").json(f"{root}/dead_letter/batch_id={batch_id}"))

        good = (batch.where("error IS NULL")
                .select("event_id", "user_id", "type", "page", "ts", "unknown_keys")
                .dropDuplicates(["event_id"]))
        silver = f"{root}/silver"
        if os.path.isdir(silver):
            seen = (spark.read.parquet(silver)
                    .where(F.col("batch_id") != batch_id).select("event_id"))
            good = good.join(seen, "event_id", "left_anti")
        good.write.mode("overwrite").parquet(f"{silver}/batch_id={batch_id}")
    finally:
        batch.unpersist()


def sessions(events: DataFrame) -> DataFrame:
    """Finished sessions per user from the parsed stream.

    Valid events only, a 10 minute watermark on ts, duplicates removed with
    dropDuplicatesWithinWatermark on event_id, then 5 minute session
    windows. Columns: user_id, start, end, events (count), checkout (true
    if the session had a checkout event).
    """
    return (events.where("error IS NULL")
            .withWatermark("ts", "10 minutes")
            .dropDuplicatesWithinWatermark(["event_id"])
            .groupBy("user_id", F.session_window("ts", "5 minutes").alias("s"))
            .agg(F.count("*").alias("events"),
                 F.max(F.col("type") == "checkout").alias("checkout"))
            .select("user_id", F.col("s.start").alias("start"),
                    F.col("s.end").alias("end"), "events", "checkout"))


# ---------------------------------------------------------------- harness
# The lesson's "current time". A real job passes F.current_timestamp().
NOW = "2026-10-05 10:00:00"


def now():
    return F.lit(NOW).cast("timestamp")


def run_ingest(spark, inbox, root, checkpoint):
    q = (parse_events(spark.readStream.text(inbox), now())
         .writeStream.foreachBatch(lambda df, i: route_batch(df, i, root))
         .option("checkpointLocation", checkpoint)
         .trigger(availableNow=True).start())
    q.awaitTermination()
    return q


def run_sessions(spark, inbox, root, checkpoint):
    df = sessions(parse_events(spark.readStream.text(inbox), now()))
    assert isinstance(df, DataFrame), "sessions must return a streaming DataFrame"
    q = (df.writeStream.format("parquet").outputMode("append")
         .option("path", f"{root}/sessions")
         .option("checkpointLocation", checkpoint)
         .trigger(availableNow=True).start())
    q.awaitTermination()
    return q


if __name__ == "__main__":
    spark = (SparkSession.builder.master("local[2]")
             .appName("StreamingMessyData")
             .config("spark.sql.shuffle.partitions", "2")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    # --- 1. parse_events on a batch DataFrame first (fast feedback) ---
    batch_lines = spark.read.text(INBOX_SOURCE)
    parsed = parse_events(batch_lines, now())
    assert isinstance(parsed, DataFrame), "parse_events must return a DataFrame"
    expected_cols = ["line", "event_id", "user_id", "type", "page", "ts", "unknown_keys", "error"]
    assert parsed.columns == expected_cols, f"parse_events columns should be {expected_cols}, got {parsed.columns}"
    errors = {r["error"]: r["n"] for r in parsed.groupBy("error").agg(F.count("*").alias("n")).collect()}
    print("Errors in all drops:", errors)
    assert errors.get(None) == 42, f"expected 42 lines without an error (duplicates included), got {errors.get(None)}"
    for reason in ("bad_json", "missing_user", "bad_ts", "future_ts"):
        assert errors.get(reason) == 1, f"expected exactly 1 line with error '{reason}', got {errors.get(reason)}"
    drifted = parsed.where(F.array_contains("unknown_keys", "app_version"))
    assert drifted.count() == 20, "the 20 tracker 2.0 lines should list app_version in unknown_keys"
    assert drifted.where("type IS NULL").count() == 0, \
        "tracker 2.0 renamed type to event_type: read both so type is never NULL"
    print("parse_events: OK")

    # --- 2. stream the drops one at a time ---
    work = tempfile.mkdtemp()
    inbox, root = f"{work}/inbox", f"{work}/lake"
    os.makedirs(inbox)
    ck_ingest, ck_sessions = f"{work}/ck_ingest", f"{work}/ck_sessions"
    dropped_late = 0
    for name in sorted(os.listdir(INBOX_SOURCE)):
        shutil.copy(f"{INBOX_SOURCE}/{name}", inbox)
        qi = run_ingest(spark, inbox, root, ck_ingest)
        assert os.path.isdir(f"{root}/silver/batch_id={qi.lastProgress.batchId}"), \
            "route_batch should write each batch's valid events to root/silver/batch_id=<id>"
        assert os.path.isdir(f"{root}/dead_letter/batch_id={qi.lastProgress.batchId}"), \
            "route_batch should write each batch's dead letters to root/dead_letter/batch_id=<id>, even when there are none"
        qs = run_sessions(spark, inbox, root, ck_sessions)
        late = sum(op.numRowsDroppedByWatermark for p in qs.recentProgress for op in p.stateOperators)
        dropped_late += late
        print(f"{name}: ingest batches {[p.batchId for p in qi.recentProgress]}, "
              f"session batches {[p.batchId for p in qs.recentProgress]}, "
              f"watermark {qs.lastProgress.eventTime.get('watermark')}, late rows {late}")

    silver = spark.read.parquet(f"{root}/silver")
    dead = spark.read.json(f"{root}/dead_letter")
    n_silver, n_dead = silver.count(), dead.count()
    print(f"silver: {n_silver} events, dead letters: {n_dead}")
    dead.orderBy("batch_id").show(truncate=60)
    assert n_dead == 4, f"expected 4 dead letters, got {n_dead}"
    assert sorted(r["error"] for r in dead.collect()) == ["bad_json", "bad_ts", "future_ts", "missing_user"], \
        "the dead letters should be one each of bad_json, bad_ts, future_ts and missing_user"
    assert n_silver == 38, f"expected 38 unique events in silver, got {n_silver} (are duplicates across batches removed?)"
    assert silver.select("event_id").distinct().count() == 38, "silver has duplicate event_ids"

    s = spark.read.parquet(f"{root}/sessions").orderBy("user_id", "start")
    s.show(truncate=False)
    rows = [(r["user_id"], r["events"], r["checkout"]) for r in s.collect()]
    assert len(rows) == 7, f"expected 7 finished sessions, got {len(rows)}"
    assert ("u2", 7, True) in rows, "u2's first session should have 7 events (one re-sent event removed) and a checkout"
    assert ("u1", 3, False) in rows and ("u4", 6, False) in rows, \
        "u1 and u4 should have sessions of 3 and 6 events (late but not too late events included)"
    assert dropped_late == 4, f"expected 4 rows dropped by the watermark, got {dropped_late}"

    # --- 3. replay the last ingest batch: the sinks must not change ---
    commits = f"{ck_ingest}/commits"
    last = max(int(f) for f in os.listdir(commits) if f.isdigit())
    for f in (str(last), f".{last}.crc"):
        if os.path.exists(f"{commits}/{f}"):
            os.remove(f"{commits}/{f}")
    q = run_ingest(spark, inbox, root, ck_ingest)
    replayed = [p.batchId for p in q.recentProgress]
    print(f"replayed ingest batch: {replayed}")
    assert replayed == [last], f"expected Spark to re-run batch {last}, got {replayed}"
    assert spark.read.parquet(f"{root}/silver").count() == 38, "a replayed batch duplicated silver rows"
    assert spark.read.json(f"{root}/dead_letter").count() == 4, "a replayed batch duplicated dead letters"

    print("All tests passed!")
    spark.stop()
