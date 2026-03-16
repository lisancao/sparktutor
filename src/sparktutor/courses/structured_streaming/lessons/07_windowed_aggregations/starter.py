"""
Windowed Aggregations — Starter Code

Detect velocity anomaly: >5 transactions per user in 10-minute windows.
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
    ("tx8", "u2", 200.0, BASE + timedelta(minutes=4)),
]


def detect_velocity_anomaly(spark, transactions_df):
    """10-min tumbling window, count per user, filter count > 5."""
    return None


if __name__ == "__main__":
    spark = SparkSession.builder.appName("PayGuardWindowed").master("local[*]").getOrCreate()

    tx_df = spark.createDataFrame(TRANSACTIONS, SCHEMA)
    result = detect_velocity_anomaly(spark, tx_df)

    assert result is not None
    rows = result.collect()
    assert len(rows) >= 1, "Expected at least one velocity anomaly (u1 has 6 tx)"
    u1_rows = [r for r in rows if r.user_id == "u1"]
    assert len(u1_rows) >= 1
    assert u1_rows[0].count > 5

    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
