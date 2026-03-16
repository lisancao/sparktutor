"""
Bronze — Raw Ingestion (Solution)

Complete bronze ingestion for ShopStream click events.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType


def bronze_clicks(spark, csv_path):
    """Ingest raw ShopStream click events into bronze."""

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

    deduped = raw.dropDuplicates(["event_id"])

    return deduped


# ---- Test harness ----
if __name__ == "__main__":
    import tempfile
    import os

    spark = SparkSession.builder.appName("BronzeClicks").master("local[*]").getOrCreate()

    tmp = tempfile.mkdtemp()
    csv_path = os.path.join(tmp, "clicks.csv")
    with open(csv_path, "w") as fh:
        fh.write("event_id,user_id,product_id,event_type,timestamp\n")
        fh.write("e1,u1,p1,click,2024-01-15T10:00:00\n")
        fh.write("e2,u2,p2,view,2024-01-15T10:01:00\n")
        fh.write("e1,u1,p1,click,2024-01-15T10:00:00\n")

    df = bronze_clicks(spark, csv_path)
    assert df is not None, "Function returned None"
    assert df.count() == 2, f"Expected 2 rows after dedup, got {df.count()}"
    assert "_ingested_at" in df.columns, "Missing _ingested_at"
    assert "_source_file" in df.columns, "Missing _source_file"
    assert df.schema["event_id"].dataType == StringType(), "event_id should be StringType"
    print("All tests passed!")
    spark.stop()
