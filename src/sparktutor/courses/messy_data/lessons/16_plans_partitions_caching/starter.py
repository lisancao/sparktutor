"""
Plans, Partitions and Caching - Exercise

Predict how many partitions a file read makes, lay the events out by day so
queries skip files, choose between repartition and coalesce, broadcast a small
lookup table, and cache a result that is reused. Every check reads the plan or
a partition count, never a timing.
"""

import contextlib
import io
import json
import os
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


def plan_text(df, mode="simple"):
    """Return what df.explain(mode) prints, as a string."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        df.explain(mode)
    return buf.getvalue()


def load_silver(spark):
    """The clean events from "JSON Drift and Quarantine", plus a `day` column."""
    raw = (spark.read.schema(EVENT_SCHEMA)
           .option("columnNameOfCorruptRecord", "_corrupt")
           .json(EVENTS))
    amount = F.coalesce(F.col("amount").try_cast("double"),
                        F.get_json_object("amount", "$.value").try_cast("double"))
    return (raw.filter(F.col("_corrupt").isNull())
            .select(F.coalesce("event_type", "event").alias("event_type"),
                    F.coalesce(F.col("user.id"), F.col("user_id")).alias("user_id"),
                    F.col("user.plan").alias("plan"),
                    amount.alias("amount"),
                    "ts",
                    F.to_date("ts").alias("day")))


# ---------------------------------------------------------------- 1. predict
def predict_file_partitions(file_sizes, splittable, max_partition_bytes,
                            open_cost, min_partitions):
    """How many partitions Spark makes for files of these sizes (bytes).

    Follows FilePartition.maxSplitBytes and getFilePartitions in Spark 4.2:
    1. total = sum(size + open_cost), bytes_per_core = total // min_partitions
    2. max_split = min(max_partition_bytes, max(open_cost, bytes_per_core))
    3. splittable files are cut into pieces of at most max_split bytes
    4. pieces are sorted largest first and packed in order: start a new
       partition when current + piece > max_split; each piece adds
       piece + open_cost to the current partition
    """
    # TODO: compute total, bytes_per_core and max_split (steps 1 and 2)
    # TODO: build the list of pieces: whole files, or max_split-sized pieces of
    #       splittable files (step 3)
    # TODO: sort the pieces largest first and pack them (step 4); return the count
    return None


# ---------------------------------------------------------------- 2. layout
def write_by_day(silver, path):
    """Write `silver` as Parquet under `path`, one folder per day (day=YYYY-MM-DD)."""
    # TODO: write Parquet partitioned by day (mode "overwrite")
    pass



def big_purchases_on(spark, path, day):
    """Read the layout back and keep user_id, amount for `day` with amount > 20."""
    # TODO: read the Parquet layout, filter on the partition column and amount,
    #       select user_id and amount
    return None


# ---------------------------------------------------------------- 3. partitions
def by_user(df, n):
    """Exactly n partitions, all rows of a user_id in the same one (a shuffle)."""
    # TODO
    return None



def one_partition(df):
    """One partition without a shuffle (for writing a single small file)."""
    # TODO
    return None


# ---------------------------------------------------------------- 4. join
def with_plan_prices(silver, prices):
    """Join each event to its plan's monthly price, broadcasting the small side."""
    # TODO: a left join on plan with a broadcast hint on prices
    return None


# ---------------------------------------------------------------- 5. cache
def cache_silver(silver):
    """Cache silver, fill the cache with one action, and return the cached DataFrame."""
    # TODO: cache, then fill the cache with one action
    return None


def release(cached):
    """Drop the cached data."""
    # TODO
    pass


# ---- Test harness ----
def files_read(df):
    """Number of files the scans of df's last run opened (classic mode; JVM plan metrics)."""
    total = 0
    stack = [df._jdf.queryExecution().executedPlan()]
    while stack:
        node = stack.pop()
        if node.nodeName().startswith("AdaptiveSparkPlan"):
            stack.append(node.executedPlan())
            continue
        metrics = node.metrics()
        if node.nodeName().startswith("Scan") and metrics.contains("numFiles"):
            total += metrics.apply("numFiles").value()
        children = node.children().iterator()
        while children.hasNext():
            stack.append(children.next())
    return total


def expected_from_json():
    """Count day-2 events with amount > 20 straight from the files, with Python's json."""
    n = 0
    for name in sorted(os.listdir(EVENTS)):
        for line in open(os.path.join(EVENTS, name)):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            amount = rec["amount"]["value"] if isinstance(rec["amount"], dict) else float(rec["amount"])
            if rec["ts"].startswith("2026-10-02") and amount > 20:
                n += 1
    return n


if __name__ == "__main__":
    spark = (SparkSession.builder
             .appName("PlansPartitionsCaching")
             .master("local[*]")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    work = tempfile.mkdtemp(prefix="plans_")

    try:
        # 1. Predict partition counts, then let Spark show the real number.
        # minPartitionNum is set so the answer does not depend on your CPU count.
        spark.conf.set("spark.sql.files.minPartitionNum", "4")
        tiny = os.path.join(work, "tiny")
        os.makedirs(tiny)
        for i in range(150):
            with open(os.path.join(tiny, f"part_{i:03d}.json"), "w") as f:
                f.write(json.dumps({"i": i}) + "\n")
        big = os.path.join(work, "big")
        os.makedirs(big)
        with open(os.path.join(big, "big.json"), "w") as f:
            line = json.dumps({"event": "view", "user_id": 1, "amount": 12.5}) + "\n"
            f.write(line * 60000)

        def sizes(folder, recursive=False):
            if recursive:
                return [os.path.getsize(os.path.join(r, n)) for r, _, fs in os.walk(folder)
                        for n in fs if not n.startswith((".", "_"))]
            return [os.path.getsize(os.path.join(folder, n)) for n in os.listdir(folder)
                    if not n.startswith((".", "_"))]

        cases = [
            ("events folder", EVENTS, "128MB", "4MB", True, lambda: spark.read.text(EVENTS)),
            ("150 tiny files", tiny, "128MB", "4MB", True, lambda: spark.read.text(tiny)),
            ("150 tiny files, openCostInBytes 1", tiny, "128MB", "1", True, lambda: spark.read.text(tiny)),
            ("one 2.9 MB file, maxPartitionBytes 512KB", big, "512KB", "4MB", True,
             lambda: spark.read.text(big)),
            ("one 2.9 MB file read whole (wholetext)", big, "512KB", "4MB", False,
             lambda: spark.read.text(big, wholetext=True)),
        ]
        to_bytes = {"128MB": 128 * 1024 * 1024, "512KB": 512 * 1024, "4MB": 4 * 1024 * 1024, "1": 1}
        for label, folder, max_bytes, open_cost, splittable, reader in cases:
            spark.conf.set("spark.sql.files.maxPartitionBytes", max_bytes)
            spark.conf.set("spark.sql.files.openCostInBytes", open_cost)
            actual = reader().rdd.getNumPartitions()
            predicted = predict_file_partitions(sizes(folder), splittable, to_bytes[max_bytes],
                                                to_bytes[open_cost], 4)
            assert predicted is not None, "predict_file_partitions() returned None"
            assert predicted == actual, (
                f"{label}: Spark made {actual} partitions but predict_file_partitions() says "
                f"{predicted}. Check max_split = min(maxPartitionBytes, max(openCost, total // "
                "min_partitions)), that each file adds size + open_cost, and that splittable files "
                "are cut into max_split pieces")
            print(f"  {label}: {actual} partitions (predicted {predicted})")
        spark.conf.unset("spark.sql.files.maxPartitionBytes")
        spark.conf.unset("spark.sql.files.openCostInBytes")
        spark.conf.unset("spark.sql.files.minPartitionNum")

        # 2. Layout by day, and a query that reads one day only
        silver = load_silver(spark)
        layout = os.path.join(work, "events_by_day")
        write_by_day(silver, layout)
        assert os.path.isdir(layout), f"write_by_day() wrote nothing at {layout}"
        days = sorted(d for d in os.listdir(layout) if not d.startswith((".", "_")))
        assert days == ["day=2026-10-01", "day=2026-10-02", "day=2026-10-03"], (
            f"Expected one folder per day named day=YYYY-MM-DD, got {days}. Use partitionBy('day')")
        back = spark.read.parquet(layout)
        assert dict(back.dtypes)["day"] == "date", (
            f"day should come back as a date (partition type inference), got {dict(back.dtypes)['day']}")

        q = big_purchases_on(spark, layout, "2026-10-02")
        assert q is not None, "big_purchases_on() returned None"
        assert q.columns == ["user_id", "amount"], f"Columns should be user_id, amount; got {q.columns}"
        text = plan_text(q)
        assert "PartitionFilters: [isnotnull(day" in text and "(day#" in text, (
            "The day filter should appear under PartitionFilters in the FileScan. Filter on the "
            "partition column `day` itself, not on ts:\n" + text)
        assert "GreaterThan(amount,20.0)" in text, (
            "amount > 20 should be pushed into the Parquet scan (PushedFilters):\n" + text)
        rows = q.collect()
        expected = expected_from_json()
        assert len(rows) == expected, f"Expected {expected} purchases over 20 on 2026-10-02, got {len(rows)}"
        assert files_read(q) == 1, (
            f"The scan should open only the day=2026-10-02 file, it opened {files_read(q)}")

        # 3. repartition versus coalesce
        spread = by_user(silver, 6)
        assert spread is not None and one_partition(silver) is not None, "by_user / one_partition returned None"
        assert spread.rdd.getNumPartitions() == 6, (
            f"by_user(df, 6) should have 6 partitions, got {spread.rdd.getNumPartitions()}")
        assert "Exchange hashpartitioning(user_id" in plan_text(spread), (
            "by_user should hash-partition by user_id (repartition(n, 'user_id')):\n" + plan_text(spread))
        per_user = (spread.select("user_id", F.spark_partition_id().alias("p"))
                    .groupBy("user_id").agg(F.countDistinct("p").alias("parts")))
        assert per_user.filter("parts > 1").count() == 0, "Every user_id should sit in exactly one partition"
        single = one_partition(silver)
        assert single.rdd.getNumPartitions() == 1, "one_partition should give 1 partition"
        assert "Exchange" not in plan_text(single), (
            "one_partition should not shuffle: use coalesce(1), not repartition(1):\n" + plan_text(single))

        # 4. Broadcast the small side
        prices = spark.createDataFrame([("free", 0.0), ("pro", 9.99)], "plan string, monthly double")
        joined = with_plan_prices(silver, prices)
        assert joined is not None, "with_plan_prices() returned None"
        jt = plan_text(joined)
        assert "BroadcastHashJoin" in jt and "BuildRight" in jt, (
            "Broadcast the prices table (the right side): F.broadcast(prices). Plan was:\n" + jt)
        assert "SortMergeJoin" not in jt, "There should be no sort-merge join"
        assert joined.count() == len(silver.collect()), "A left join on plan must keep every event"

        # 5. Cache, reuse, release
        cached = cache_silver(load_silver(spark))
        assert cached is not None, "cache_silver() returned None"
        assert cached.is_cached, "cache_silver should cache the DataFrame"
        assert cached.storageLevel.useMemory and cached.storageLevel.useDisk, (
            f"cache() uses memory and disk; got {cached.storageLevel}")
        storage = spark.sparkContext._jsc.sc().getRDDStorageInfo()
        assert any(info.numCachedPartitions() > 0 for info in storage), (
            "The cache is still empty: cache() is lazy, run an action (count) inside cache_silver")
        reuse = cached.groupBy("day").agg(F.round(F.sum("amount"), 2).alias("revenue"))
        assert "InMemoryTableScan" in plan_text(reuse), (
            "A query on the cached DataFrame should read InMemoryTableScan:\n" + plan_text(reuse))
        print("Revenue per day (from the cache):")
        reuse.orderBy("day").show()
        release(cached)
        assert not cached.is_cached, "release() should unpersist the DataFrame"

        print("Plan of big_purchases_on:")
        print(text)
        print("Files read:", files_read(q), "of", len(back.inputFiles()))
        print("All tests passed!")
    finally:
        spark.stop()
