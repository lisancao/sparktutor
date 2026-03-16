"""
Bronze — Raw Ingestion (Starter)

Implement bronze_clicks(spark, csv_path) that ingests ShopStream click
events CSV with schema-on-read, metadata columns, and deduplication.

Schema: event_id, user_id, product_id, event_type, timestamp (all StringType)
Metadata: _ingested_at, _source_file
Dedup: by event_id
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType


def bronze_clicks(spark, csv_path):
    """Ingest raw ShopStream click events into bronze."""

    # TODO: Define all-StringType schema
    schema = None

    # TODO: Read CSV with schema, add _ingested_at and _source_file
    raw = None

    # TODO: Deduplicate by event_id
    deduped = None

    return deduped


# ---- Test harness (do not modify below this line) ----
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
