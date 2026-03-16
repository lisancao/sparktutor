"""
Checkpointing & Fault Tolerance — Starter Code

1. Build checkpoint config for writeStream.
2. Process batches (simulating micro-batches) and aggregate.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, TimestampType


def build_checkpointed_query_config(checkpoint_path, output_mode):
    """Return dict with checkpoint_location and output_mode."""
    return None


def process_batches_with_aggregation(spark, batch_dfs):
    """Union all batches, aggregate by user_id (count, sum amount)."""
    return None


if __name__ == "__main__":
    spark = SparkSession.builder.appName("PayGuardCheckpoint").master("local[*]").getOrCreate()

    config = build_checkpointed_query_config("/checkpoints/fraud", "update")
    assert config is not None
    assert config.get("checkpoint_location") == "/checkpoints/fraud"
    assert config.get("output_mode") == "update"

    schema = StructType([
        StructField("tx_id", StringType(), False),
        StructField("user_id", StringType(), False),
        StructField("amount", DoubleType(), False),
        StructField("event_time", TimestampType(), False),
    ])
    b1 = spark.createDataFrame([("tx1", "u1", 100.0, "2024-01-15 10:00:00")], schema)
    b2 = spark.createDataFrame([("tx2", "u1", 50.0, "2024-01-15 10:01:00"), ("tx3", "u2", 200.0, "2024-01-15 10:02:00")], schema)
    batches = [b1, b2]

    result = process_batches_with_aggregation(spark, batches)
    assert result is not None
    rows = result.collect()
    u1 = next(r for r in rows if r.user_id == "u1")
    assert u1.tx_count == 2 and u1.amount_sum == 150.0

    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
