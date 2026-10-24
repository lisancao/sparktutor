"""
Join Strategies - Solution

The same join planned three ways: broadcast hash, shuffled hash, and sort
merge, with plans captured through explain() rather than the JVM.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType
)
import contextlib
import io
import random


def generate_users(n=1000):
    cities = ["New York", "San Francisco", "Chicago", "Seattle", "Austin"]
    random.seed(42)
    return [(i, f"user_{i}", random.choice(cities)) for i in range(n)]


def generate_orders(n=5000, max_user_id=1000):
    random.seed(99)
    return [
        (i, random.randint(0, max_user_id - 1), round(random.uniform(10, 500), 2))
        for i in range(n)
    ]


USER_SCHEMA = StructType([
    StructField("user_id", IntegerType(), False),
    StructField("name", StringType(), False),
    StructField("city", StringType(), False),
])

ORDER_SCHEMA = StructType([
    StructField("order_id", IntegerType(), False),
    StructField("user_id", IntegerType(), False),
    StructField("amount", DoubleType(), False),
])


def plan_text(df, mode="simple"):
    """Return what df.explain(mode) prints (works in Classic and Connect)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        df.explain(mode=mode)
    return buf.getvalue()


def join_comparison(spark):
    """Compare broadcast, shuffled hash, and sort merge joins."""

    users_df = spark.createDataFrame(generate_users(), USER_SCHEMA)
    orders_df = spark.createDataFrame(generate_orders(), ORDER_SCHEMA)

    broadcast_result = orders_df.join(f.broadcast(users_df), "user_id")
    broadcast_plan = plan_text(broadcast_result)

    shuffle_hash_result = orders_df.join(users_df.hint("shuffle_hash"), "user_id")
    shuffle_hash_plan = plan_text(shuffle_hash_result)

    original = spark.conf.get("spark.sql.autoBroadcastJoinThreshold")
    try:
        spark.conf.set("spark.sql.autoBroadcastJoinThreshold", "-1")
        smj_result = orders_df.join(users_df, "user_id")
        smj_plan = plan_text(smj_result)
    finally:
        spark.conf.set("spark.sql.autoBroadcastJoinThreshold", original)

    return {
        "broadcast_result": broadcast_result,
        "shuffle_hash_result": shuffle_hash_result,
        "smj_result": smj_result,
        "broadcast_plan": broadcast_plan,
        "shuffle_hash_plan": shuffle_hash_plan,
        "smj_plan": smj_plan,
    }


# ---- Test harness ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("JoinTest")
        .master("local[*]")
        .getOrCreate())

    threshold_before = spark.conf.get("spark.sql.autoBroadcastJoinThreshold")
    result = join_comparison(spark)
    assert result is not None, "Function returned None"
    for key in ["broadcast_result", "shuffle_hash_result", "smj_result",
                "broadcast_plan", "shuffle_hash_plan", "smj_plan"]:
        assert result.get(key) is not None, f"{key} is missing or None"

    counts = {k: result[k].count() for k in ["broadcast_result", "shuffle_hash_result", "smj_result"]}
    assert set(counts.values()) == {5000}, f"Every strategy should return 5000 rows, got {counts}"

    assert "BroadcastHashJoin" in result["broadcast_plan"], "Broadcast plan should use BroadcastHashJoin"
    assert "ShuffledHashJoin" in result["shuffle_hash_plan"], "shuffle_hash hint should give ShuffledHashJoin"
    assert "SortMergeJoin" in result["smj_plan"], "With broadcast disabled the plan should use SortMergeJoin"
    assert spark.conf.get("spark.sql.autoBroadcastJoinThreshold") == threshold_before, \
        "Restore autoBroadcastJoinThreshold when you are done"

    def join_line(plan):
        return next(l.strip() for l in plan.splitlines() if "Join" in l)

    print(f"Every strategy produced {counts['smj_result']} rows")
    print("Broadcast:   ", join_line(result["broadcast_plan"]))
    print("Shuffle hash:", join_line(result["shuffle_hash_plan"]))
    print("Sort merge:  ", join_line(result["smj_plan"]))
    print("All tests passed!")
    spark.stop()