"""
Your First Stream — Starter Code

Simulate a file-based stream: process transaction batches with the same
logic a readStream would use. Returns combined summary for all batches.
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

BATCH_1 = [
    ("tx1", "u1", "m1", 100.0, "2024-01-15 10:00:00"),
    ("tx2", "u2", "m2", 50.0, "2024-01-15 10:01:00"),
]
BATCH_2 = [
    ("tx3", "u1", "m1", 75.0, "2024-01-15 10:02:00"),
    ("tx4", "u3", "m3", 200.0, "2024-01-15 10:03:00"),
]
BATCH_3 = [
    ("tx5", "u1", "m2", 25.0, "2024-01-15 10:04:00"),
]


def process_transaction_stream(spark, batch_dfs):
    """Process each batch (simulating micro-batches from readStream).
    Select tx_id, user_id, amount, event_time. Union all and return."""
    return None


if __name__ == "__main__":
    spark = SparkSession.builder.appName("PayGuardFirstStream").master("local[*]").getOrCreate()

    batch1_df = spark.createDataFrame(BATCH_1, SCHEMA)
    batch2_df = spark.createDataFrame(BATCH_2, SCHEMA)
    batch3_df = spark.createDataFrame(BATCH_3, SCHEMA)
    batches = [batch1_df, batch2_df, batch3_df]

    result = process_transaction_stream(spark, batches)

    assert result is not None, "process_transaction_stream returned None"
    rows = result.collect()
    assert len(rows) == 5, f"Expected 5 rows, got {len(rows)}"
    assert "tx_id" in result.columns and "user_id" in result.columns
    assert "amount" in result.columns and "event_time" in result.columns

    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
