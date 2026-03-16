"""
Capstone — Production ShopStream Pipeline (Starter)

Implement run_production_pipeline(spark, data_dir) that:
- Bronze: clicks (CSV), payments (JSON)
- Silver: cast, validate, enrich clicks with products
- Gold: daily revenue, conversion rate
- Monitoring: report with bronze_rows, silver_valid, silver_quarantine, gold_rows, quality_score
"""

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
    # TODO: Read CSV with schema, add metadata, dedup
    return None


def bronze_payments(spark, json_path):
    # TODO: Read JSON with schema, add metadata, dedup
    return None


def silver_clicks(spark, bronze_df):
    # TODO: Cast timestamp, split valid/quarantine
    return (None, None)


def silver_payments(spark, bronze_df):
    # TODO: Cast amount, created_at, validate amount > 0
    return (None, None)


def run_production_pipeline(spark, data_dir):
    """
    Run full pipeline. Return report dict with bronze_rows, silver_valid,
    silver_quarantine, gold_rows, quality_score.
    """
    import os
    # TODO: bronze clicks and payments
    # TODO: silver both
    # TODO: gold daily revenue from payments
    # TODO: gold conversion (simplified: count clicks and payments per day)
    # TODO: build report
    return {}


# ---- Test harness (do not modify below this line) ----
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
