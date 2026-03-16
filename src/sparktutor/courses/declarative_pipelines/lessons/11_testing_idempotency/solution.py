"""
Testing & Idempotency (Solution)

Unit tests for bronze, silver, gold with idempotency verification.
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
    tmp = tempfile.mkdtemp()
    csv_path = os.path.join(tmp, "clicks.csv")
    with open(csv_path, "w") as fh:
        fh.write("event_id,user_id,product_id,event_type,timestamp\n")
        fh.write("e1,u1,p1,click,2024-01-15 10:00:00\n")
        fh.write("e2,u2,p2,view,2024-01-15 10:01:00\n")
        fh.write("e1,u1,p1,click,2024-01-15 10:00:00\n")
    df = bronze_clicks(spark, csv_path)
    assert df.count() == 2, f"Expected 2 after dedup, got {df.count()}"


def test_silver_quarantine(spark):
    bronze_data = [
        ("e1", "u1", "p1", "click", "2024-01-15 10:00:00"),
        ("e2", "u2", "p2", "view", "2024-01-15 10:01:00"),
        ("e3", "u3", "p3", "click", "invalid"),
    ]
    schema = StructType([
        StructField("event_id", StringType()),
        StructField("user_id", StringType()),
        StructField("product_id", StringType()),
        StructField("event_type", StringType()),
        StructField("timestamp", StringType()),
    ])
    bronze_df = spark.createDataFrame(bronze_data, schema)
    valid, quarantine = silver_clicks(spark, bronze_df)
    assert valid.count() == 2, f"Expected 2 valid, got {valid.count()}"
    assert quarantine.count() == 1, f"Expected 1 quarantine, got {quarantine.count()}"


def test_gold_idempotent(spark):
    orders_data = [
        ("2024-01-15 10:00:00", "Electronics", 99.99),
        ("2024-01-15 10:30:00", "Electronics", 49.99),
    ]
    orders_df = spark.createDataFrame(orders_data, ["created_at", "category", "amount"])
    orders_df = orders_df.withColumn("created_at", f.to_timestamp("created_at"))
    gold1 = gold_daily_revenue_by_category(orders_df).collect()
    gold2 = gold_daily_revenue_by_category(orders_df).collect()
    assert gold1 == gold2, "Gold should be idempotent"


# ---- Test harness ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("Testing").master("local[*]").getOrCreate()
    test_bronze_dedup(spark)
    test_silver_quarantine(spark)
    test_gold_idempotent(spark)
    print("All tests passed!")
    spark.stop()
