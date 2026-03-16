"""
Multi-Mode Fraud Detection — Solution

Stateless rules (continuous-compatible) and stateful rules (micro-batch).
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, TimestampType,
)

TX_SCHEMA = StructType([
    StructField("tx_id", StringType(), False),
    StructField("user_id", StringType(), False),
    StructField("merchant_id", StringType(), False),
    StructField("amount", DoubleType(), False),
    StructField("event_time", TimestampType(), False),
])

ALERT_COLUMNS = ["tx_id", "user_id", "rule_name", "severity", "evidence"]


def realtime_stateless_rules(transactions_df, blocked_merchants):
    """Continuous-mode compatible: amount threshold + blocklist."""

    amount_alerts = (transactions_df
        .filter(f.col("amount") > 1000)
        .select(
            f.col("tx_id"),
            f.col("user_id"),
            f.lit("amount_threshold").alias("rule_name"),
            f.lit("high").alias("severity"),
            f.concat(f.lit("amount="), f.col("amount").cast("string")).alias("evidence"),
        ))

    blocklist_alerts = (transactions_df
        .filter(f.col("merchant_id").isin(blocked_merchants))
        .select(
            f.col("tx_id"),
            f.col("user_id"),
            f.lit("blocklist").alias("rule_name"),
            f.lit("medium").alias("severity"),
            f.concat(f.lit("merchant="), f.col("merchant_id")).alias("evidence"),
        ))

    return amount_alerts.union(blocklist_alerts)


def nearrealtime_stateful_rules(transactions_df):
    """Async micro-batch compatible: velocity detection with window + watermark."""

    windowed = (transactions_df
        .withWatermark("event_time", "10 minutes")
        .groupBy(
            f.window("event_time", "10 minutes"),
            "user_id",
        )
        .agg(f.count("*").alias("tx_count"))
        .filter(f.col("tx_count") > 3))

    return windowed.select(
        f.lit("N/A").alias("tx_id"),
        f.col("user_id"),
        f.lit("velocity").alias("rule_name"),
        f.lit("high").alias("severity"),
        f.concat(f.lit("count="), f.col("tx_count").cast("string")).alias("evidence"),
    )


# ---- Test harness ----
if __name__ == "__main__":
    from datetime import datetime, timedelta

    spark = (SparkSession.builder
        .appName("MultiModeTest")
        .master("local[*]")
        .config("spark.sql.shuffle.partitions", "4")
        .getOrCreate())

    base = datetime(2024, 1, 15, 10, 0, 0)
    tx_data = [
        ("tx1", "u1", "m1", 50.0, base),
        ("tx2", "u1", "m1", 75.0, base + timedelta(minutes=1)),
        ("tx3", "u1", "m2", 60.0, base + timedelta(minutes=2)),
        ("tx4", "u1", "m1", 40.0, base + timedelta(minutes=3)),
        ("tx5", "u2", "m3", 1500.0, base + timedelta(minutes=1)),
        ("tx6", "u3", "m_blocked", 200.0, base + timedelta(minutes=2)),
        ("tx7", "u3", "m1", 2000.0, base + timedelta(minutes=3)),
    ]
    blocked = ["m_blocked", "m_bad"]
    tx_df = spark.createDataFrame(tx_data, TX_SCHEMA)

    stateless = realtime_stateless_rules(tx_df, blocked)
    assert stateless is not None, "realtime_stateless_rules returned None"
    stateless_rows = stateless.collect()

    amount_hits = [r for r in stateless_rows if r.rule_name == "amount_threshold"]
    assert len(amount_hits) == 2, f"Expected 2 amount alerts (tx5=$1500, tx7=$2000), got {len(amount_hits)}"

    block_hits = [r for r in stateless_rows if r.rule_name == "blocklist"]
    assert len(block_hits) == 1, f"Expected 1 blocklist alert (tx6), got {len(block_hits)}"

    for col in ALERT_COLUMNS:
        assert col in stateless.columns, f"Missing column: {col}"

    plan_str = stateless._jdf.queryExecution().logical().toString()
    assert "Aggregate" not in plan_str, "Stateless rules must not use aggregation"

    stateful = nearrealtime_stateful_rules(tx_df)
    assert stateful is not None, "nearrealtime_stateful_rules returned None"
    velocity_rows = stateful.collect()
    u1_alerts = [r for r in velocity_rows if r.user_id == "u1"]
    assert len(u1_alerts) >= 1, f"Expected velocity alert for u1 (4 tx in 10 min), got {len(u1_alerts)}"

    print("All tests passed!")
    print("\n--- Stateless alerts ---")
    stateless.show(truncate=False)
    print("\n--- Stateful alerts ---")
    stateful.show(truncate=False)
    spark.stop()
