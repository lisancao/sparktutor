"""
Bronze — Multi-Source Ingestion (Solution)

Complete bronze ingestion for clicks, payments, and inventory.
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
    ]),
    "inventory": StructType([
        StructField("sku", StringType()),
        StructField("quantity", LongType()),
        StructField("warehouse_id", StringType()),
        StructField("updated_at", StringType()),
    ]),
}


def bronze_clicks(spark, csv_path):
    """Ingest raw click events."""
    raw = (spark.read.csv(csv_path, header=True, schema=SCHEMAS["clicks"])
        .withColumn("_ingested_at", f.current_timestamp())
        .withColumn("_source_file", f.input_file_name()))
    return raw.dropDuplicates(["event_id"])


def bronze_payments(spark, json_path):
    """Ingest raw payment events."""
    raw = (spark.read.json(json_path, schema=SCHEMAS["payments"])
        .withColumn("_ingested_at", f.current_timestamp())
        .withColumn("_source_file", f.input_file_name()))
    return raw.dropDuplicates(["payment_id"])


def bronze_inventory(spark, json_path):
    """Ingest raw inventory updates."""
    raw = (spark.read.json(json_path, schema=SCHEMAS["inventory"])
        .withColumn("_ingested_at", f.current_timestamp())
        .withColumn("_source_file", f.input_file_name()))
    return raw.dropDuplicates(["sku", "warehouse_id"])


# ---- Test harness ----
if __name__ == "__main__":
    import tempfile
    import os

    spark = SparkSession.builder.appName("BronzeMulti").master("local[*]").getOrCreate()

    tmp = tempfile.mkdtemp()

    clicks_path = os.path.join(tmp, "clicks.csv")
    with open(clicks_path, "w") as fh:
        fh.write("event_id,user_id,product_id,event_type,timestamp\n")
        fh.write("e1,u1,p1,click,2024-01-15T10:00:00\n")
        fh.write("e2,u2,p2,view,2024-01-15T10:01:00\n")

    payments_path = os.path.join(tmp, "payments.json")
    with open(payments_path, "w") as fh:
        fh.write('{"payment_id":"pay1","amount":99.99,"customer_id":"c1","created_at":"2024-01-15T10:00:00"}\n')
        fh.write('{"payment_id":"pay2","amount":49.99,"customer_id":"c2","created_at":"2024-01-15T10:01:00"}\n')

    inventory_path = os.path.join(tmp, "inventory.json")
    with open(inventory_path, "w") as fh:
        fh.write('{"sku":"SKU1","quantity":100,"warehouse_id":"WH1","updated_at":"2024-01-15T10:00:00"}\n')
        fh.write('{"sku":"SKU2","quantity":50,"warehouse_id":"WH1","updated_at":"2024-01-15T10:01:00"}\n')

    clicks = bronze_clicks(spark, clicks_path)
    payments = bronze_payments(spark, payments_path)
    inventory = bronze_inventory(spark, inventory_path)

    assert clicks.count() == 2, f"clicks: expected 2, got {clicks.count()}"
    assert payments.count() == 2, f"payments: expected 2, got {payments.count()}"
    assert inventory.count() == 2, f"inventory: expected 2, got {inventory.count()}"
    assert "_ingested_at" in clicks.columns and "_ingested_at" in payments.columns
    print("All tests passed!")
    spark.stop()
