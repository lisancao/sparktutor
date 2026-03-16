"""
Batch vs Streaming Transaction Count — Solution

Same transformation logic for batch and streaming; only the source differs.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, TimestampType

TRANSACTIONS_DATA = [
    ("tx1", "u1", 100.0, "2024-01-15 10:00:00"),
    ("tx2", "u2", 50.0, "2024-01-15 10:01:00"),
    ("tx3", "u1", 75.0, "2024-01-15 10:02:00"),
    ("tx4", "u3", 200.0, "2024-01-15 10:03:00"),
    ("tx5", "u1", 25.0, "2024-01-15 10:04:00"),
]

SCHEMA = StructType([
    StructField("tx_id", StringType(), False),
    StructField("user_id", StringType(), False),
    StructField("amount", DoubleType(), False),
    StructField("event_time", TimestampType(), False),
])


def transaction_count_batch(spark):
    """Batch version: read from DataFrame, count per user, order by count desc."""
    input_df = spark.createDataFrame(TRANSACTIONS_DATA, SCHEMA)
    return (input_df
        .groupBy("user_id")
        .count()
        .orderBy(f.col("count").desc()))


def transaction_count_streaming_logic(spark, input_df):
    """Streaming logic: same transformations as batch, applied to input_df."""
    return (input_df
        .groupBy("user_id")
        .count()
        .orderBy(f.col("count").desc()))


if __name__ == "__main__":
    spark = SparkSession.builder.appName("PayGuardBatchVsStream").master("local[*]").getOrCreate()

    batch_df = spark.createDataFrame(TRANSACTIONS_DATA, SCHEMA)
    batch_result = transaction_count_batch(spark)
    stream_result = transaction_count_streaming_logic(spark, batch_df)

    assert batch_result is not None, "transaction_count_batch returned None"
    assert stream_result is not None, "transaction_count_streaming_logic returned None"

    batch_rows = batch_result.collect()
    stream_rows = stream_result.collect()
    assert len(batch_rows) == len(stream_rows), "Results should have same row count"
    for br, sr in zip(batch_rows, stream_rows):
        assert br.user_id == sr.user_id and br.count == sr.count, "Results should match"

    u1_row = next(r for r in batch_rows if r.user_id == "u1")
    assert u1_row.count == 3, f"u1 should have 3 transactions, got {u1_row.count}"

    print("All tests passed!")
    batch_result.show(truncate=False)
    spark.stop()
