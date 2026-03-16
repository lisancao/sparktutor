"""
Stateful Aggregations — Starter Code

Running aggregation by user_id and merchant_id: tx_count and amount_sum.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, TimestampType

SCHEMA = StructType([
    StructField("tx_id", StringType(), False),
    StructField("user_id", StringType(), False),
    StructField("merchant_id", StringType(), False),
    StructField("amount", DoubleType(), False),
    StructField("event_time", TimestampType(), False),
])

TRANSACTIONS = [
    ("tx1", "u1", "m1", 100.0, "2024-01-15 10:00:00"),
    ("tx2", "u1", "m1", 50.0, "2024-01-15 10:01:00"),
    ("tx3", "u1", "m2", 75.0, "2024-01-15 10:02:00"),
    ("tx4", "u2", "m1", 200.0, "2024-01-15 10:03:00"),
    ("tx5", "u1", "m1", 25.0, "2024-01-15 10:04:00"),
]


def running_aggregation(spark, transactions_df):
    """Group by user_id, merchant_id. Compute tx_count and amount_sum."""
    return None


if __name__ == "__main__":
    spark = SparkSession.builder.appName("PayGuardStateful").master("local[*]").getOrCreate()

    tx_df = spark.createDataFrame(TRANSACTIONS, SCHEMA)
    result = running_aggregation(spark, tx_df)

    assert result is not None
    assert "tx_count" in result.columns and "amount_sum" in result.columns
    rows = result.collect()
    u1_m1 = next(r for r in rows if r.user_id == "u1" and r.merchant_id == "m1")
    assert u1_m1.tx_count == 3 and u1_m1.amount_sum == 175.0
    u1_m2 = next(r for r in rows if r.user_id == "u1" and r.merchant_id == "m2")
    assert u1_m2.tx_count == 1 and u1_m2.amount_sum == 75.0

    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
