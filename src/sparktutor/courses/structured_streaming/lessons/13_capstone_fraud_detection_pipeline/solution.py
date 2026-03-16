"""
Capstone — Real-Time Fraud Detection Pipeline — Solution

Complete pipeline: enrich, velocity, amount, blocklist rules, output alerts.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, TimestampType
from datetime import datetime, timedelta

TX_SCHEMA = StructType([
    StructField("tx_id", StringType(), False),
    StructField("user_id", StringType(), False),
    StructField("merchant_id", StringType(), False),
    StructField("amount", DoubleType(), False),
    StructField("event_time", TimestampType(), False),
])


def run_fraud_detection_pipeline(spark, transactions_df, accounts_df, blocked_merchants):
    """Enrich, apply velocity/amount/blocklist rules, union alerts, add severity."""
    enriched = transactions_df.join(accounts_df, "user_id", "left")
    enriched_with_window = enriched.withColumn("window", f.window("event_time", "10 minutes"))

    velocity_violations = (enriched_with_window
        .withWatermark("event_time", "10 minutes")
        .groupBy("window", "user_id")
        .count()
        .filter(f.col("count") > 5))

    velocity_alerts = (enriched_with_window
        .join(velocity_violations, ["window", "user_id"])
        .select(
            f.col("tx_id"),
            f.col("user_id"),
            f.lit("velocity").alias("rule_name"),
            f.lit("high").alias("severity"),
            f.concat(f.lit("count="), f.col("count").cast("string")).alias("evidence")
        ))

    amount_alerts = (enriched
        .filter(f.col("amount") > 1000)
        .select(
            f.col("tx_id"),
            f.col("user_id"),
            f.lit("amount_threshold").alias("rule_name"),
            f.lit("high").alias("severity"),
            f.concat(f.lit("amount="), f.col("amount").cast("string")).alias("evidence")
        ))

    blocked_list = blocked_merchants if isinstance(blocked_merchants, list) else [r.merchant_id for r in blocked_merchants.collect()]
    blocklist_alerts = (enriched
        .filter(f.col("merchant_id").isin(blocked_list))
        .select(
            f.col("tx_id"),
            f.col("user_id"),
            f.lit("blocklist").alias("rule_name"),
            f.lit("medium").alias("severity"),
            f.concat(f.lit("merchant="), f.col("merchant_id")).alias("evidence")
        ))

    return velocity_alerts.union(amount_alerts).union(blocklist_alerts)


if __name__ == "__main__":
    spark = SparkSession.builder.appName("PayGuardCapstone").master("local[*]").getOrCreate()

    base = datetime(2024, 1, 15, 10, 0, 0)
    tx_data = [
        ("tx1", "u1", "m1", 100.0, base),
        ("tx2", "u1", "m1", 50.0, base + timedelta(minutes=1)),
        ("tx3", "u1", "m2", 75.0, base + timedelta(minutes=2)),
        ("tx4", "u1", "m1", 40.0, base + timedelta(minutes=3)),
        ("tx5", "u1", "m2", 60.0, base + timedelta(minutes=4)),
        ("tx6", "u1", "m1", 80.0, base + timedelta(minutes=5)),
        ("tx7", "u2", "m3", 1500.0, base + timedelta(minutes=2)),
        ("tx8", "u3", "m_blocked", 200.0, base + timedelta(minutes=1)),
    ]
    accounts_data = [("u1", "standard"), ("u2", "premium"), ("u3", "standard")]
    blocked = ["m_blocked"]

    tx_df = spark.createDataFrame(tx_data, TX_SCHEMA)
    accounts_df = spark.createDataFrame(accounts_data, ["user_id", "tier"])

    alerts = run_fraud_detection_pipeline(spark, tx_df, accounts_df, blocked)

    assert alerts is not None
    rows = alerts.collect()
    assert len(rows) >= 2
    velocity_alerts = [r for r in rows if "velocity" in r.rule_name.lower()]
    amount_alerts = [r for r in rows if "amount" in r.rule_name.lower()]
    blocklist_alerts = [r for r in rows if "blocklist" in r.rule_name.lower()]
    assert len(velocity_alerts) >= 1
    assert len(amount_alerts) >= 1
    assert len(blocklist_alerts) >= 1
    assert "severity" in alerts.columns

    print("All tests passed!")
    alerts.show(truncate=False)
    spark.stop()
