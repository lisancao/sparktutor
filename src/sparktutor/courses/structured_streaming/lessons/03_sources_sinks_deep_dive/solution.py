"""
Sources & Sinks Deep Dive — Solution

Process transactions and route alerts to multiple destinations.
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
    ("tx2", "u2", 600.0, "2024-01-15 10:01:00"),
    ("tx3", "u1", 75.0, "2024-01-15 10:02:00"),
    ("tx4", "u3", 1200.0, "2024-01-15 10:03:00"),
    ("tx5", "u1", 25.0, "2024-01-15 10:04:00"),
]


def process_and_route_alerts(spark, transactions_df):
    """Filter amount > 500, add alert_type='high_amount'."""
    alerts = (transactions_df
        .filter(f.col("amount") > 500)
        .withColumn("alert_type", f.lit("high_amount")))
    return (alerts, alerts)


if __name__ == "__main__":
    spark = SparkSession.builder.appName("PayGuardSourcesSinks").master("local[*]").getOrCreate()

    tx_df = spark.createDataFrame(TRANSACTIONS, SCHEMA)
    console_df, file_df = process_and_route_alerts(spark, tx_df)

    assert console_df is not None and file_df is not None
    assert console_df.columns == file_df.columns
    rows = console_df.collect()
    assert len(rows) == 2, f"Expected 2 alerts (tx2=600, tx4=1200), got {len(rows)}"
    assert "alert_type" in console_df.columns
    assert all(r.alert_type == "high_amount" for r in rows)
    amounts = [r.amount for r in rows]
    assert 600 in amounts and 1200 in amounts

    print("All tests passed!")
    console_df.show(truncate=False)
    spark.stop()
