"""
Your First Stream — Solution

Simulate file-based stream processing with batch DataFrames.
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
    """Process each batch (simulating micro-batches from readStream)."""
    summaries = [df.select("tx_id", "user_id", "amount", "event_time") for df in batch_dfs]
    if not summaries:
        empty_schema = StructType([
            StructField("tx_id", StringType(), False),
            StructField("user_id", StringType(), False),
            StructField("amount", DoubleType(), False),
            StructField("event_time", TimestampType(), False),
        ])
        return spark.createDataFrame([], empty_schema)
    result = summaries[0]
    for df in summaries[1:]:
        result = result.union(df)
    return result


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
