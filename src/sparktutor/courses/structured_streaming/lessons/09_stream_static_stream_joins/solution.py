"""
Stream-Static & Stream-Stream Joins — Solution

Enrich with accounts and match transactions to auth events.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, TimestampType, IntegerType
from datetime import datetime, timedelta

TX_SCHEMA = StructType([
    StructField("tx_id", StringType(), False),
    StructField("user_id", StringType(), False),
    StructField("amount", DoubleType(), False),
    StructField("event_time", TimestampType(), False),
])


def enrich_with_accounts(spark, transactions_df, accounts_df):
    """Left join transactions with accounts on user_id."""
    return transactions_df.join(accounts_df, "user_id", "left")


def match_transactions_to_auth(spark, transactions_df, auth_events_df):
    """Join transactions with auth events on user_id and time range."""
    tx = transactions_df.alias("tx")
    auth = auth_events_df.alias("auth")
    return (tx.join(auth, f.col("tx.user_id") == f.col("auth.user_id"))
        .filter(f.col("auth.auth_time") <= f.col("tx.event_time"))
        .filter(f.col("tx.event_time") <= f.col("auth.auth_time") + f.expr("INTERVAL 10 MINUTES"))
        .select(
            f.col("tx.tx_id"),
            f.col("tx.user_id"),
            f.col("tx.amount"),
            f.col("tx.event_time"),
            f.col("auth.auth_time").alias("auth_time")
        ))


if __name__ == "__main__":
    spark = SparkSession.builder.appName("PayGuardJoins").master("local[*]").getOrCreate()

    tx_data = [
        ("tx1", "u1", 100.0, datetime(2024, 1, 15, 10, 5, 0)),
        ("tx2", "u2", 200.0, datetime(2024, 1, 15, 10, 10, 0)),
    ]
    accounts_data = [
        ("u1", "premium", "low"),
        ("u2", "standard", "medium"),
    ]
    auth_data = [
        ("u1", datetime(2024, 1, 15, 10, 0, 0)),
        ("u2", datetime(2024, 1, 15, 10, 8, 0)),
    ]

    tx_df = spark.createDataFrame(tx_data, ["tx_id", "user_id", "amount", "event_time"])
    accounts_df = spark.createDataFrame(accounts_data, ["user_id", "tier", "risk_level"])
    auth_df = spark.createDataFrame(auth_data, ["user_id", "auth_time"])

    enriched = enrich_with_accounts(spark, tx_df, accounts_df)
    assert enriched is not None
    assert "tier" in enriched.columns
    r1 = enriched.filter(f.col("tx_id") == "tx1").collect()[0]
    assert r1.tier == "premium"

    matched = match_transactions_to_auth(spark, tx_df, auth_df)
    assert matched is not None
    assert matched.count() >= 1

    print("All tests passed!")
    enriched.show(truncate=False)
    matched.show(truncate=False)
    spark.stop()
