"""
Why Spark for Messy Data, and How It Runs Your Code - Solution

Make Spark report facts about its own work: how many partitions a
DataFrame has, how many jobs and tasks an action starts, whether a plan
contains a shuffle, which processes run your Python functions, and how a
task that crashes once is retried.
"""

import contextlib
import io
import os

from pyspark import TaskContext
from pyspark.sql import SparkSession, functions as F


def settle(spark):
    """Wait until Spark's status tracker has recorded every finished job.

    Spark records job and stage progress on a background thread, so right
    after an action returns the tracker can be a moment behind. This helper
    waits for that thread to catch up. You don't need to change it.
    """
    spark.sparkContext._jsc.sc().listenerBus().waitUntilEmpty()


def partition_count(df):
    """The number of partitions of `df`."""
    return df.rdd.getNumPartitions()


def run_and_report(spark, group, action):
    """Run `action()` as job group `group` and report what Spark did.

    Returns a dict:
      result:       whatever action() returned
      jobs:         how many jobs Spark ran for it
      tasks:        completed tasks per stage that ran, in stage id order
                    (stages Spark skipped, with 0 completed tasks, left out)
      failed_tasks: how many task attempts failed, over all those stages
    """
    sc = spark.sparkContext
    sc.setJobGroup(group, f"exercise: {group}")
    result = action()
    settle(spark)

    tracker = sc.statusTracker()
    stage_ids = []
    for job_id in tracker.getJobIdsForGroup(group):
        stage_ids.extend(tracker.getJobInfo(job_id).stageIds)
    stages = [tracker.getStageInfo(s) for s in sorted(set(stage_ids))]
    return {
        "result": result,
        "jobs": len(tracker.getJobIdsForGroup(group)),
        "tasks": [s.numCompletedTasks for s in stages if s.numCompletedTasks > 0],
        "failed_tasks": sum(s.numFailedTasks for s in stages),
    }


def has_exchange(df):
    """True when the physical plan of `df` contains a shuffle (an Exchange)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        df.explain()
    return "Exchange" in buf.getvalue()


def python_worker_pids(spark, partitions):
    """The set of process ids that ran a Python UDF over `partitions` partitions."""
    @F.udf("int")
    def worker_pid(_):
        return os.getpid()

    rows = spark.range(0, 100, 1, partitions).select(worker_pid("id").alias("pid")).collect()
    return {r["pid"] for r in rows}


def flaky_sum(spark):
    """Sum of id * 10 for id in 0..7 (4 partitions), with a UDF that crashes once.

    The UDF raises on the first attempt of the task for partition 1, and
    works on every other attempt. With retries allowed, Spark reruns that
    task and the answer is still right.
    """
    @F.udf("long")
    def times_ten(x):
        ctx = TaskContext.get()
        if ctx.partitionId() == 1 and ctx.attemptNumber() == 0:
            raise RuntimeError("simulated crash on the first attempt")
        return x * 10

    df = spark.range(0, 8, 1, 4).select(times_ten("id").alias("v"))
    return df.agg(F.sum("v").alias("total")).collect()[0]["total"]


# ---- Test harness ----
if __name__ == "__main__":
    # local[4,2]: 4 worker threads, and each task may be tried 2 times
    spark = (SparkSession.builder
             .appName("WhySpark")
             .master("local[4,2]")
             .getOrCreate())
    spark.sparkContext.setLogLevel("OFF")

    try:
        # 1. Partitions
        n = partition_count(spark.range(0, 100, 1, 6))
        assert n == 6, f"spark.range(0, 100, 1, 6) has 6 partitions, partition_count returned {n}"
        n_default = partition_count(spark.range(100))
        assert n_default == spark.sparkContext.defaultParallelism == 4, (
            f"spark.range(100) without a partition count should use the default parallelism "
            f"(4 for local[4,2]); got {n_default}")
        print(f"Partitions: range with 6 slices -> {n}, range with the default -> {n_default}")

        # 2. Lazy evaluation: transformations alone run no job
        numbers = spark.range(0, 600, 1, 6)
        lazy = run_and_report(spark, "lazy", lambda: numbers.filter("id % 7 = 0").withColumn("sq", F.col("id") ** 2))
        assert lazy is not None, "run_and_report returned None: complete TODO 2"
        for key in ["result", "jobs", "tasks", "failed_tasks"]:
            assert key in lazy, f"run_and_report must return a dict with the key {key!r}"
        assert lazy["jobs"] == 0, (
            f"filter and withColumn are transformations and should start no job; got {lazy['jobs']} jobs. "
            "Count the job ids of the group with statusTracker().getJobIdsForGroup(group)")

        # 3. An action without a shuffle: one job, one stage, one task per partition
        narrow = run_and_report(spark, "narrow", lambda: numbers.filter("id % 7 = 0").collect())
        assert len(narrow["result"]) == 86, f"Expected 86 multiples of 7 below 600, got {len(narrow['result'])}"
        assert narrow["jobs"] == 1 and narrow["tasks"] == [6], (
            f"collect() over 6 partitions with no shuffle runs 1 job with one stage of 6 tasks; "
            f"got jobs={narrow['jobs']} tasks={narrow['tasks']}")

        # 4. An action with a shuffle: two stages that run
        grouped = numbers.groupBy((F.col("id") % 3).alias("k")).count()
        wide = run_and_report(spark, "wide", lambda: grouped.collect())
        assert sorted((r["k"], r["count"]) for r in wide["result"]) == [(0, 200), (1, 200), (2, 200)]
        assert wide["tasks"] == [6, 1], (
            f"groupBy needs a shuffle: 6 map tasks, then (after adaptive execution merges the "
            f"tiny shuffle partitions) 1 reduce task. Expected tasks [6, 1], got {wide['tasks']}. "
            "Leave out stages with 0 completed tasks (they were skipped)")

        # 5. Schema inference reads the data, an explicit schema does not
        inferred = run_and_report(spark, "infer", lambda: spark.read.json("data/messy/events"))
        declared = run_and_report(spark, "declare", lambda: spark.read.schema("event STRING").json("data/messy/events"))
        assert inferred["jobs"] >= 1, "spark.read.json without a schema should run a job to infer the schema"
        assert declared["jobs"] == 0, f"With a schema, reading should run no job until an action; got {declared['jobs']}"

        # 6. Shuffles in the plan
        assert has_exchange(grouped) is True, "groupBy(...).count() needs a shuffle: its plan has an Exchange"
        assert has_exchange(numbers.filter("id > 3")) is False, "A filter needs no shuffle: no Exchange in its plan"

        # 7. Python UDFs run in Python worker processes, not in this process
        pids = python_worker_pids(spark, 4)
        assert pids, "python_worker_pids returned nothing: complete TODO 4"
        assert os.getpid() not in pids, (
            "The UDF reported this script's own process id. Return os.getpid() from inside the UDF, "
            "not a value computed on the driver")

        # 8. A task that crashes once is retried
        print("Running the flaky job (its first attempt of partition 1 crashes on purpose)")
        flaky = run_and_report(spark, "flaky", lambda: flaky_sum(spark))
        assert flaky["result"] == 280, f"sum of id * 10 for 0..7 is 280, got {flaky['result']}"
        assert flaky["failed_tasks"] == 1, (
            f"Exactly one task attempt should fail (partition 1, attempt 0); got {flaky['failed_tasks']}. "
            "Raise only when TaskContext.get().partitionId() == 1 and attemptNumber() == 0")

        print(f"Lazy transformations: {lazy['jobs']} jobs")
        print(f"Filter + collect:     {narrow['jobs']} job, tasks per stage {narrow['tasks']}")
        print(f"groupBy + collect:    {wide['jobs']} jobs, tasks per stage {wide['tasks']}")
        print(f"read.json inference:  {inferred['jobs']} job(s); with a schema: {declared['jobs']}")
        print(f"Driver pid {os.getpid()}, Python worker pids {sorted(pids)}")
        print(f"Flaky job: total {flaky['result']}, failed task attempts {flaky['failed_tasks']}, "
              f"tasks per stage {flaky['tasks']}")
        print("All tests passed!")
    finally:
        spark.stop()
