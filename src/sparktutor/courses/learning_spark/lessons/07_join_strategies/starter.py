"""
Join Strategies - Starter Code

Implement the `join_comparison` function that:
1. Creates a "users" DataFrame (1000 rows: user_id, name, city)
2. Creates an "orders" DataFrame (5000 rows: order_id, user_id, amount)
3. Performs a broadcast join (hint the users table)
4. Performs a sort merge join (disable broadcast threshold)
5. Returns both results and their explain plan strings

This exercise demonstrates the difference between join strategies.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType
)
import random


def generate_users(n=1000):
    """Generate sample user data."""
    cities = ["New York", "San Francisco", "Chicago", "Seattle", "Austin"]
    random.seed(42)
    return [(i, f"user_{i}", random.choice(cities)) for i in range(n)]


def generate_orders(n=5000, max_user_id=1000):
    """Generate sample order data."""
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


def join_comparison(spark):
    """Compare broadcast join vs sort merge join."""

    users_df = spark.createDataFrame(generate_users(), USER_SCHEMA)
    orders_df = spark.createDataFrame(generate_orders(), ORDER_SCHEMA)

    # TODO: Broadcast join — join orders with users using broadcast hint on users
    broadcast_result = None  # Replace

    # Capture broadcast join plan
    broadcast_plan = broadcast_result._jdf.queryExecution().simpleString()

    # TODO: Sort merge join — disable broadcast by setting threshold to -1,
    #       then join orders with users (no broadcast hint)
    # Set config here
    smj_result = None  # Replace

    # Capture sort merge join plan
    smj_plan = smj_result._jdf.queryExecution().simpleString()

    # TODO: Reset the threshold back to default (10MB = 10485760)
    # Your code here

    return {
        "broadcast_result": broadcast_result,
        "smj_result": smj_result,
        "broadcast_plan": broadcast_plan,
        "smj_plan": smj_plan,
    }


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("JoinTest")
        .master("local[*]")
        .getOrCreate())

    result = join_comparison(spark)
    assert result is not None, "Function returned None"
    bc_count = result["broadcast_result"].count()
    smj_count = result["smj_result"].count()
    assert bc_count == smj_count, f"Counts differ: broadcast={bc_count}, smj={smj_count}"
    assert bc_count == 5000, f"Expected 5000 rows, got {bc_count}"
    assert "Broadcast" in result["broadcast_plan"] or "broadcast" in result["broadcast_plan"].lower(), \
        "Broadcast plan should mention broadcast"
    print(f"Both joins produced {bc_count} rows")
    print(f"\nBroadcast plan contains 'broadcast': {'broadcast' in result['broadcast_plan'].lower()}")
    print(f"SMJ plan contains 'SortMerge' or 'sort': {'sort' in result['smj_plan'].lower()}")
    print("All tests passed!")
    spark.stop()
