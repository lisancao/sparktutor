"""
Gold — Business Aggregations (Starter)

Implement gold_daily_revenue_by_category and gold_hourly_conversion.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, TimestampType


def gold_daily_revenue_by_category(orders_df):
    """Group by date and category, sum amount, count orders."""
    # TODO: groupBy to_date(created_at), category
    # TODO: agg sum(amount), count(*)
    return None


def gold_hourly_conversion(clicks_df, orders_df):
    """
    For each hour: count clicks (event_type='click') and orders.
    conversion_rate = orders / clicks. Handle clicks=0.
    """
    # TODO: groupBy hour for clicks and orders separately
    # TODO: join on hour
    # TODO: conversion_rate = when(clicks>0, orders/clicks).otherwise(None)
    return None


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("Gold").master("local[*]").getOrCreate()

    orders_data = [
        ("2024-01-15 10:00:00", "Electronics", 99.99),
        ("2024-01-15 10:30:00", "Electronics", 49.99),
        ("2024-01-15 11:00:00", "Home", 29.99),
    ]
    orders_df = spark.createDataFrame(orders_data, ["created_at", "category", "amount"])
    orders_df = orders_df.withColumn("created_at", f.to_timestamp("created_at"))

    clicks_data = [
        ("2024-01-15 10:00:00", "click"),
        ("2024-01-15 10:15:00", "view"),
        ("2024-01-15 10:30:00", "click"),
    ]
    clicks_df = spark.createDataFrame(clicks_data, ["timestamp", "event_type"])
    clicks_df = clicks_df.withColumn("timestamp", f.to_timestamp("timestamp"))

    orders_for_conv = spark.createDataFrame(
        [("2024-01-15 10:00:00",), ("2024-01-15 10:45:00",)],
        ["created_at"]
    ).withColumn("created_at", f.to_timestamp("created_at"))

    daily = gold_daily_revenue_by_category(orders_df)
    assert daily is not None
    assert "revenue" in daily.columns
    assert "order_count" in daily.columns
    assert daily.count() >= 1

    hourly = gold_hourly_conversion(clicks_df, orders_for_conv)
    assert hourly is not None
    assert "conversion_rate" in hourly.columns
    print("All tests passed!")
    spark.stop()
