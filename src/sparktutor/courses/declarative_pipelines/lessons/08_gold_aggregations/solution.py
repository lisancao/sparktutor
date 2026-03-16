"""
Gold — Business Aggregations (Solution)

Daily revenue by category and hourly conversion rates.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, TimestampType


def gold_daily_revenue_by_category(orders_df):
    """Group by date and category, sum amount, count orders."""
    return (orders_df
        .groupBy(f.to_date("created_at").alias("date"), "category")
        .agg(f.sum("amount").alias("revenue"), f.count("*").alias("order_count")))


def gold_hourly_conversion(clicks_df, orders_df):
    """
    For each hour: count clicks (event_type='click') and orders.
    conversion_rate = orders / clicks. Handle clicks=0.
    """
    clicks_hourly = (clicks_df
        .filter(f.col("event_type") == "click")
        .groupBy(f.date_trunc("hour", "timestamp").alias("hour"))
        .agg(f.count("*").alias("clicks")))
    orders_hourly = (orders_df
        .groupBy(f.date_trunc("hour", "created_at").alias("hour"))
        .agg(f.count("*").alias("orders")))
    joined = clicks_hourly.join(orders_hourly, "hour", "left")
    return joined.withColumn(
        "conversion_rate",
        f.when(f.col("clicks") > 0, f.col("orders") / f.col("clicks"))
        .otherwise(None)
    )


# ---- Test harness ----
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
