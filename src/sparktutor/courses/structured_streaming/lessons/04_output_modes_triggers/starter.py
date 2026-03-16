"""
Output Modes & Triggers — Starter Code

Aggregate transactions by user_id: count and sum(amount).
Same logic works with update or complete output mode in streaming.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, TimestampType

SCHEMA = StructType([
    StructField("tx_id", StringType(), False),
    StructField("user_id", StringType(), False),
    StructField("amount", DoubleType(), False),
    StructField("event_time", TimestampType(), False),
])

TRANSACTIONS = [
    ("tx1", "u1", 100.0, "2024-01-15 10:00:00"),
    ("tx2", "u2", 50.0, "2024-01-15 10:01:00"),
    ("tx3", "u1", 75.0, "2024-01-15 10:02:00"),
    ("tx4", "u3", 200.0, "2024-01-15 10:03:00"),
    ("tx5", "u1", 25.0, "2024-01-15 10:04:00"),
]


def aggregate_by_user(spark, transactions_df):
    """Group by user_id, compute tx_count and amount_sum."""
    return None


if __name__ == "__main__":
    spark = SparkSession.builder.appName("PayGuardOutputModes").master("local[*]").getOrCreate()

    tx_df = spark.createDataFrame(TRANSACTIONS, SCHEMA)
    result = aggregate_by_user(spark, tx_df)

    assert result is not None
    assert "tx_count" in result.columns and "amount_sum" in result.columns
    rows = result.collect()
    u1 = next(r for r in rows if r.user_id == "u1")
    assert u1.tx_count == 3 and u1.amount_sum == 200.0
    u2 = next(r for r in rows if r.user_id == "u2")
    assert u2.tx_count == 1 and u2.amount_sum == 50.0

    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
