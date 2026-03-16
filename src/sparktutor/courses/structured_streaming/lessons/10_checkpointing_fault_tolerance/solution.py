"""
Checkpointing & Fault Tolerance — Solution

Checkpoint config and batch processing simulation.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, TimestampType


def build_checkpointed_query_config(checkpoint_path, output_mode):
    """Return dict with checkpoint_location and output_mode."""
    return {
        "checkpoint_location": checkpoint_path,
        "output_mode": output_mode,
    }


def process_batches_with_aggregation(spark, batch_dfs):
    """Union all batches, aggregate by user_id (count, sum amount)."""
    if not batch_dfs:
        from pyspark.sql.types import LongType
        empty_schema = StructType([
            StructField("user_id", StringType(), False),
            StructField("tx_count", LongType(), False),
            StructField("amount_sum", DoubleType(), False),
        ])
        return spark.createDataFrame([], empty_schema)
    combined = batch_dfs[0]
    for df in batch_dfs[1:]:
        combined = combined.union(df)
    return (combined
        .groupBy("user_id")
        .agg(
            f.count("*").alias("tx_count"),
            f.sum("amount").alias("amount_sum")
        ))


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
