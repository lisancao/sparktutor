"""
Join Strategies - Starter Code

Implement the `join_comparison` function that:
1. Creates a small users DataFrame and a larger orders DataFrame
2. Performs a broadcast hash join using the f.broadcast() hint
3. Performs a shuffled hash join using the "shuffle_hash" hint
4. Performs a sort merge join by setting autoBroadcastJoinThreshold to -1
5. Captures each plan with plan_text() while its setting is in effect
6. Restores the original threshold in a finally block
7. Returns a dict with the three results and three plans

This exercise shows how hints and configuration steer the join planner.
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

    # TODO: Broadcast hash join: orders_df joined to f.broadcast(users_df) on "user_id"
    broadcast_result = None  # Replace
    broadcast_plan = None  # plan_text(...)

    # TODO: Shuffled hash join: use users_df.hint("shuffle_hash")
    shuffle_hash_result = None  # Replace
    shuffle_hash_plan = None  # plan_text(...)

    # TODO: Save the current spark.sql.autoBroadcastJoinThreshold value
    original = None  # Replace

    # TODO: In a try block, set the threshold to "-1", join without hints,
    #       and capture the plan. In the finally block, restore `original`.
    smj_result = None  # Replace
    smj_plan = None  # Replace

    return {
        "broadcast_result": broadcast_result,
        "shuffle_hash_result": shuffle_hash_result,
        "smj_result": smj_result,
        "broadcast_plan": broadcast_plan,
        "shuffle_hash_plan": shuffle_hash_plan,
        "smj_plan": smj_plan,
    }


# ---- Test harness (do not modify below this line) ----
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