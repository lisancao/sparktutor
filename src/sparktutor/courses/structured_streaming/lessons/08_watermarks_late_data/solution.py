"""
Watermarks & Late Data — Solution

Velocity detection with watermark for streaming compatibility.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, TimestampType
from datetime import datetime, timedelta

SCHEMA = StructType([
    StructField("tx_id", StringType(), False),
    StructField("user_id", StringType(), False),
    StructField("amount", DoubleType(), False),
    StructField("event_time", TimestampType(), False),
])

BASE = datetime(2024, 1, 15, 10, 0, 0)
TRANSACTIONS = [
    ("tx1", "u1", 10.0, BASE),
    ("tx2", "u1", 20.0, BASE + timedelta(minutes=1)),
    ("tx3", "u1", 30.0, BASE + timedelta(minutes=2)),
    ("tx4", "u1", 40.0, BASE + timedelta(minutes=3)),
    ("tx5", "u1", 50.0, BASE + timedelta(minutes=4)),
    ("tx6", "u1", 60.0, BASE + timedelta(minutes=5)),
    ("tx7", "u2", 100.0, BASE + timedelta(minutes=2)),
]


def detect_velocity_with_watermark(spark, transactions_df):
    """10-min watermark, 10-min window, count per user, filter > 5."""
    return (transactions_df
        .withWatermark("event_time", "10 minutes")
        .groupBy(f.window("event_time", "10 minutes"), "user_id")
        .count()
        .filter(f.col("count") > 5))


if __name__ == "__main__":
    spark = SparkSession.builder.appName("PayGuardWatermarks").master("local[*]").getOrCreate()

    tx_df = spark.createDataFrame(TRANSACTIONS, SCHEMA)
    result = detect_velocity_with_watermark(spark, tx_df)

    assert result is not None
    rows = result.collect()
    u1_rows = [r for r in rows if r.user_id == "u1"]
    assert len(u1_rows) >= 1
    assert u1_rows[0].count > 5

    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
