"""
Capstone — Production ShopStream Pipeline (Solution)

Complete production pipeline with bronze, silver, gold, and monitoring.
"""

import os
from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, LongType

SCHEMAS = {
    "clicks": StructType([
        StructField("event_id", StringType()),
        StructField("user_id", StringType()),
        StructField("product_id", StringType()),
        StructField("event_type", StringType()),
        StructField("timestamp", StringType()),
    ]),
    "payments": StructType([
        StructField("payment_id", StringType()),
        StructField("amount", DoubleType()),
        StructField("customer_id", StringType()),
        StructField("created_at", StringType()),
        StructField("category", StringType()),
    ]),
}


def bronze_clicks(spark, csv_path):
    if not os.path.exists(csv_path):
        return spark.createDataFrame([], SCHEMAS["clicks"])
    raw = (spark.read.csv(csv_path, header=True, schema=SCHEMAS["clicks"])
        .withColumn("_ingested_at", f.current_timestamp())
        .withColumn("_source_file", f.input_file_name()))
    return raw.dropDuplicates(["event_id"])


def bronze_payments(spark, json_path):
    if not os.path.exists(json_path):
        return spark.createDataFrame([], SCHEMAS["payments"])
    raw = (spark.read.json(json_path, schema=SCHEMAS["payments"])
        .withColumn("_ingested_at", f.current_timestamp())
        .withColumn("_source_file", f.input_file_name()))
    return raw.dropDuplicates(["payment_id"])


def silver_clicks(spark, bronze_df):
    with_cast = bronze_df.withColumn("_ts_cast", f.to_timestamp(f.col("timestamp")))
    valid = with_cast.filter(f.col("_ts_cast").isNotNull()).withColumn("timestamp", f.col("_ts_cast")).drop("_ts_cast")
    quarantine = with_cast.filter(f.col("_ts_cast").isNull()).withColumn("_quarantine_reason", f.lit("timestamp_cast_failed")).withColumn("_quarantine_at", f.current_timestamp()).drop("_ts_cast")
    return (valid, quarantine)


def silver_payments(spark, bronze_df):
    with_cast = bronze_df.withColumn("created_at", f.to_timestamp(f.col("created_at")))
    valid = with_cast.filter((f.col("amount") > 0) & (f.col("created_at").isNotNull()))
    quarantine = with_cast.filter(~((f.col("amount") > 0) & (f.col("created_at").isNotNull()))).withColumn("_quarantine_reason", f.lit("validation_failed")).withColumn("_quarantine_at", f.current_timestamp())
    return (valid, quarantine)


def run_production_pipeline(spark, data_dir):
    clicks_path = os.path.join(data_dir, "clicks.csv")
    payments_path = os.path.join(data_dir, "payments.json")

    bronze_c = bronze_clicks(spark, clicks_path)
    bronze_p = bronze_payments(spark, payments_path)
    bronze_rows = bronze_c.count() + bronze_p.count()

    valid_c, quarantine_c = silver_clicks(spark, bronze_c)
    valid_p, quarantine_p = silver_payments(spark, bronze_p)
    silver_valid = valid_c.count() + valid_p.count()
    silver_quarantine = quarantine_c.count() + quarantine_p.count()

    gold_revenue = (valid_p
        .withColumn("date", f.to_date("created_at"))
        .groupBy("date", "category")
        .agg(f.sum("amount").alias("revenue"), f.count("*").alias("order_count")))
    gold_rows = gold_revenue.count()

    total_silver = silver_valid + silver_quarantine
    quality_score = silver_valid / total_silver if total_silver > 0 else 1.0

    return {
        "bronze_rows": bronze_rows,
        "silver_valid": silver_valid,
        "silver_quarantine": silver_quarantine,
        "gold_rows": gold_rows,
        "quality_score": quality_score,
    }


# ---- Test harness ----
if __name__ == "__main__":
    import tempfile
    import os

    spark = SparkSession.builder.appName("Capstone").master("local[*]").getOrCreate()

    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, "clicks.csv"), "w") as fh:
        fh.write("event_id,user_id,product_id,event_type,timestamp\n")
        fh.write("e1,u1,p1,click,2024-01-15 10:00:00\n")
    with open(os.path.join(tmp, "payments.json"), "w") as fh:
        fh.write('{"payment_id":"pay1","amount":99.99,"customer_id":"c1","created_at":"2024-01-15 10:00:00","category":"Electronics"}\n')

    report = run_production_pipeline(spark, tmp)
    assert "bronze_rows" in report
    assert "silver_valid" in report
    assert "silver_quarantine" in report
    assert "gold_rows" in report
    assert "quality_score" in report
    assert report["bronze_rows"] >= 1
    print("All tests passed!")
    spark.stop()
