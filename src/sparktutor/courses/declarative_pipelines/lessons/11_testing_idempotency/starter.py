"""
Testing & Idempotency (Starter)

Implement test_bronze_dedup, test_silver_quarantine, test_gold_idempotent.
"""

import tempfile
import os
from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType


def bronze_clicks(spark, csv_path):
    schema = StructType([
        StructField("event_id", StringType()),
        StructField("user_id", StringType()),
        StructField("product_id", StringType()),
        StructField("event_type", StringType()),
        StructField("timestamp", StringType()),
    ])
    raw = (spark.read.csv(csv_path, header=True, schema=schema)
        .withColumn("_ingested_at", f.current_timestamp())
        .withColumn("_source_file", f.input_file_name()))
    return raw.dropDuplicates(["event_id"])


def silver_clicks(spark, bronze_df):
    with_cast = bronze_df.withColumn("_ts_cast", f.to_timestamp(f.col("timestamp")))
    valid = with_cast.filter(f.col("_ts_cast").isNotNull()).withColumn("timestamp", f.col("_ts_cast")).drop("_ts_cast")
    quarantine = with_cast.filter(f.col("_ts_cast").isNull()).withColumn("_quarantine_reason", f.lit("timestamp_cast_failed")).withColumn("_quarantine_at", f.current_timestamp()).drop("_ts_cast")
    return (valid, quarantine)


def gold_daily_revenue_by_category(orders_df):
    return (orders_df
        .groupBy(f.to_date("created_at").alias("date"), "category")
        .agg(f.sum("amount").alias("revenue"), f.count("*").alias("order_count")))


def test_bronze_dedup(spark):
    # TODO: Create CSV with duplicate event_id, run bronze_clicks, assert count == 2
    pass


def test_silver_quarantine(spark):
    # TODO: Create bronze with invalid timestamp row, run silver_clicks, assert valid=2, quarantine=1
    pass


def test_gold_idempotent(spark):
    # TODO: Create orders_df, run gold twice, assert results equal
    pass


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("Testing").master("local[*]").getOrCreate()
    test_bronze_dedup(spark)
    test_silver_quarantine(spark)
    test_gold_idempotent(spark)
    print("All tests passed!")
    spark.stop()
