"""
Observability: Listeners, Metrics and Profiling Executors - Solution

The harness runs a small application with the event log on: a skewed
aggregation through a Python UDF, and a sort that is forced to spill.
While the application is alive it also reads the same numbers from the
Spark UI's REST API. Then it stops the application and starts a second
one that only has the event log, which is where your code comes in:

1. load_events: read the event log of a finished application (rolling
   folder, zstd-compressed JSON lines) as a DataFrame.
2. stage_descriptions: map each stage to the job description that was set
   with setJobDescription, found in the StageSubmitted event's Properties.
3. task_metrics: one row per finished task, pulled out of nested,
   space-named fields, including Python time from the task's
   accumulables.
4. diagnose: one row per stage with counts, sums, skew and flags.

The checks compare your numbers with the REST API's, so they hold on any
machine (no timing thresholds on exact values).
"""

import json
import os
import tempfile
import urllib.request

from pyspark.sql import SparkSession, functions as F

PYTHON_TIME = "time to execute Python code"


# ---- 1. Load the event log ----
def load_events(spark, log_dir):
    """Return a DataFrame with one row per event of the single application
    whose event log is in log_dir. Since 4.0 the log is a rolling folder
    eventlog_v2_<appId>/ holding events_<n>_<appId>.zstd files (plus an
    appstatus_* marker file that holds no events). Spark reads .zstd JSON
    directly since 4.1.
    """
    return spark.read.json(os.path.join(log_dir, "eventlog_v2_*", "events_*"))


# ---- 2. Which job does each stage belong to? ----
def stage_descriptions(events):
    """Return a DataFrame (stage_id long, description string): for every
    SparkListenerStageSubmitted event, the stage id and the
    "spark.job.description" property (dots in a field name need backticks).
    """
    return (events.where(F.col("Event") == "SparkListenerStageSubmitted")
            .select(F.col("`Stage Info`.`Stage ID`").cast("long").alias("stage_id"),
                    F.col("Properties.`spark.job.description`").alias("description"))
            .dropDuplicates(["stage_id"]))


# ---- 3. One row per task ----
def task_metrics(events):
    """Return a DataFrame with one row per SparkListenerTaskEnd whose
    Task End Reason is Success, with columns:
      stage_id, task_id, run_ms, records_in, shuffle_bytes_read,
      mem_spill, disk_spill, python_ms
    records_in = Input Metrics.Records Read + Shuffle Read Metrics.Total
    Records Read. python_ms = sum of the "Update" of the accumulables named
    PYTHON_TIME in Task Info.Accumulables (0 when there are none). Mind the
    types: SQL accumulator updates are written as JSON strings.
    """
    tm = "`Task Metrics`"
    srm = f"{tm}.`Shuffle Read Metrics`"
    acc = F.col("`Task Info`.Accumulables")
    python_updates = F.filter(acc, lambda a: a["Name"] == PYTHON_TIME)
    python_ms = F.aggregate(python_updates, F.lit(0).cast("long"),
                            lambda s, a: s + a["Update"].cast("long"))
    return (events.where((F.col("Event") == "SparkListenerTaskEnd")
                         & (F.col("`Task End Reason`.Reason") == "Success"))
            .select(F.col("`Stage ID`").cast("long").alias("stage_id"),
                    F.col("`Task Info`.`Task ID`").cast("long").alias("task_id"),
                    F.col(f"{tm}.`Executor Run Time`").cast("long").alias("run_ms"),
                    (F.col(f"{tm}.`Input Metrics`.`Records Read`")
                     + F.col(f"{srm}.`Total Records Read`")).cast("long").alias("records_in"),
                    (F.col(f"{srm}.`Local Bytes Read`")
                     + F.col(f"{srm}.`Remote Bytes Read`")).cast("long").alias("shuffle_bytes_read"),
                    F.col(f"{tm}.`Memory Bytes Spilled`").cast("long").alias("mem_spill"),
                    F.col(f"{tm}.`Disk Bytes Spilled`").cast("long").alias("disk_spill"),
                    python_ms.alias("python_ms")))


# ---- 4. One row per stage ----
def diagnose(tasks, descriptions):
    """Return one row per stage, ordered by stage_id, with columns:
      stage_id, description, tasks, run_ms, records_in, max_records,
      median_records, record_skew, disk_spill, python_ms, flags
    run_ms, records_in, disk_spill and python_ms are sums over the
    stage's tasks. median_records is the exact median (percentile with
    0.5). record_skew = max_records / median_records, NULL when the median
    is 0. flags is an array<string>, built in this order:
      "skew"   when tasks > 1 and record_skew >= 4
      "spill"  when disk_spill > 0
      "python" when python_ms > 0 and python_ms >= run_ms / 2
    """
    per_stage = (tasks.groupBy("stage_id").agg(
        F.count("*").alias("tasks"),
        F.sum("run_ms").alias("run_ms"),
        F.sum("records_in").alias("records_in"),
        F.max("records_in").alias("max_records"),
        F.percentile("records_in", 0.5).alias("median_records"),
        F.sum("disk_spill").alias("disk_spill"),
        F.sum("python_ms").alias("python_ms")))
    skew = F.when(F.col("median_records") > 0,
                  F.col("max_records") / F.col("median_records"))
    flags = F.array_compact(F.array(
        F.when((F.col("tasks") > 1) & (F.col("record_skew") >= 4), F.lit("skew")),
        F.when(F.col("disk_spill") > 0, F.lit("spill")),
        F.when((F.col("python_ms") > 0) & (F.col("python_ms") >= F.col("run_ms") / 2),
               F.lit("python"))))
    return (per_stage.withColumn("record_skew", skew)
            .withColumn("flags", flags)
            .join(descriptions, "stage_id", "left")
            .select("stage_id", "description", "tasks", "run_ms", "records_in",
                    "max_records", "median_records", "record_skew", "disk_spill",
                    "python_ms", "flags")
            .orderBy("stage_id"))


# ---- Harness ----
def run_workload(log_dir):
    """Run the application to diagnose; return the REST API's stage list."""
    spark = (SparkSession.builder.master("local[2]").appName("observed")
             .config("spark.eventLog.enabled", "true")
             .config("spark.eventLog.dir", log_dir)
             # A fixed stage layout: AQE would coalesce and re-plan stages
             .config("spark.sql.adaptive.enabled", "false")
             .config("spark.sql.shuffle.partitions", "4")
             # Force the sorter to spill after 2000 rows (an internal setting)
             .config("spark.shuffle.spill.numElementsForceSpillThreshold", "2000")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    sc = spark.sparkContext

    @F.udf("long")
    def score(user, n):
        # Deliberately slow Python: the work grows with the number of rows
        h = 0
        for i in range(1000):
            h = (h * 31 + n + i + len(user)) % 1000003
        return h

    # 90% of the events belong to one user: a hot key
    events = (spark.range(0, 60000, numPartitions=2)
              .withColumn("user", F.when(F.col("id") % 10 < 9, F.lit("bot-7"))
                          .otherwise(F.concat(F.lit("u"), (F.col("id") % 97).cast("string"))))
              .withColumn("n", F.col("id") % 13))

    sc.setJobDescription("skewed_scoring")
    (events.repartition(4, "user")
     .select("user", score("user", "n").alias("s"))
     .groupBy("user").agg(F.sum("s").alias("s"))
     .write.format("noop").mode("overwrite").save())

    sc.setJobDescription("spilling_sort")
    (spark.range(0, 30000, numPartitions=2)
     .select((F.col("id") * 7919 % 30011).alias("k"), F.col("id"))
     .repartition(2, "k").sortWithinPartitions("k")
     .write.format("noop").mode("overwrite").save())

    url = f"{sc.uiWebUrl}/api/v1/applications/{sc.applicationId}/stages"
    stages = json.load(urllib.request.urlopen(url))
    spark.stop()  # finishes the event log (appstatus_* loses .inprogress)
    return stages


if __name__ == "__main__":
    log_dir = tempfile.mkdtemp(prefix="eventlog_")
    rest = {s["stageId"]: s for s in run_workload(log_dir)}
    print(f"Workload finished: {len(rest)} stages reported by the REST API")

    spark = SparkSession.builder.master("local[2]").appName("diagnosis").getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")

    events = load_events(spark, log_dir)
    assert events is not None, "load_events must return a DataFrame"
    kinds = {r["Event"] for r in events.select("Event").distinct().collect()}
    assert {"SparkListenerApplicationStart", "SparkListenerTaskEnd",
            "SparkListenerApplicationEnd"} <= kinds, (
        f"load_events should read every event of the application; found {sorted(kinds)}")
    print(f"Events read: {events.count()} ({len(kinds)} kinds)")

    descriptions = stage_descriptions(events)
    assert descriptions is not None, "stage_descriptions must return a DataFrame"
    desc = {r["stage_id"]: r["description"] for r in descriptions.collect()}
    assert set(desc) == set(rest), (
        f"stage_descriptions found stages {sorted(desc)}, the REST API {sorted(rest)}")
    assert set(desc.values()) == {"skewed_scoring", "spilling_sort"}, (
        f"Every stage should carry its job description, got {sorted(set(map(str, desc.values())))}")

    tasks = task_metrics(events)
    assert tasks is not None, "task_metrics must return a DataFrame"
    expected_cols = ["stage_id", "task_id", "run_ms", "records_in", "shuffle_bytes_read",
                     "mem_spill", "disk_spill", "python_ms"]
    assert tasks.columns == expected_cols, f"task_metrics columns: {tasks.columns}, expected {expected_cols}"
    n_tasks = tasks.count()
    assert n_tasks == sum(s["numCompleteTasks"] for s in rest.values()), (
        f"task_metrics has {n_tasks} rows, the REST API counts "
        f"{sum(s['numCompleteTasks'] for s in rest.values())} completed tasks")
    assert dict(tasks.dtypes)["python_ms"] in ("bigint", "int"), (
        "python_ms must be numeric: accumulator Update values are strings in the log")

    report = diagnose(tasks, descriptions)
    assert report is not None, "diagnose must return a DataFrame"
    rows = report.collect()
    print("\nDiagnosis")
    report.show(truncate=False)

    for r in rows:
        s = rest[r["stage_id"]]
        label = f"stage {r['stage_id']} ({r['description']})"
        assert r["tasks"] == s["numCompleteTasks"], f"{label}: tasks {r['tasks']} != REST {s['numCompleteTasks']}"
        assert r["run_ms"] == s["executorRunTime"], f"{label}: run_ms {r['run_ms']} != REST executorRunTime {s['executorRunTime']}"
        assert r["records_in"] == s["inputRecords"] + s["shuffleReadRecords"], (
            f"{label}: records_in {r['records_in']} != REST inputRecords + shuffleReadRecords "
            f"{s['inputRecords'] + s['shuffleReadRecords']}")
        assert r["disk_spill"] == s["diskBytesSpilled"], f"{label}: disk_spill {r['disk_spill']} != REST {s['diskBytesSpilled']}"

    mem = {r["stage_id"]: r["m"] for r in tasks.groupBy("stage_id").agg(F.sum("mem_spill").alias("m")).collect()}
    for sid, s in rest.items():
        assert mem.get(sid) == s["memoryBytesSpilled"], (
            f"stage {sid}: mem_spill sums to {mem.get(sid)}, REST memoryBytesSpilled is "
            f"{s['memoryBytesSpilled']}")

    flagged = {f:[r["stage_id"] for r in rows if f in r["flags"]] for f in ("skew", "spill", "python")}
    scoring = [r for r in rows if r["description"] == "skewed_scoring"]
    sorting = [r for r in rows if r["description"] == "spilling_sort"]
    udf_stage = max(scoring, key=lambda r: r["python_ms"])
    assert udf_stage["python_ms"] > 0, "The scoring job ran a Python UDF, so some stage must have python_ms > 0"
    assert flagged["skew"] == [udf_stage["stage_id"]], (
        f"Only the UDF stage of skewed_scoring (stage {udf_stage['stage_id']}) is skewed; "
        f"flagged {flagged['skew']}")
    assert udf_stage["record_skew"] is not None and udf_stage["record_skew"] >= 4
    assert flagged["spill"] and all(r["description"] == "spilling_sort" for r in rows if "spill" in r["flags"]), (
        f"The spilling_sort job should be the one that spills; flagged {flagged['spill']}")
    assert sum(r["disk_spill"] for r in sorting) > 0, "spilling_sort should report disk spill"
    assert "python" in udf_stage["flags"], (
        f"The UDF stage spent {udf_stage['python_ms']} of {udf_stage['run_ms']} ms in Python; "
        "it should carry the python flag")

    hot = (tasks.where(F.col("stage_id") == udf_stage["stage_id"])
           .orderBy(F.desc("records_in")).first())
    print(f"Hot task: task {hot['task_id']} read {hot['records_in']} of "
          f"{udf_stage['records_in']} rows in stage {udf_stage['stage_id']} "
          f"and spent {hot['python_ms']} ms in Python")
    spark.stop()
    print("\nAll tests passed!")
