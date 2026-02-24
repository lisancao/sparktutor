"""
Bronze Layer - Solution

Complete bronze ingestion with schema-on-read, metadata columns,
and deduplication.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType


def bronze_orders(spark, csv_path):
    """Ingest raw orders CSV into a bronze DataFrame."""

    schema = StructType([
        StructField("order_id", StringType()),
        StructField("product", StringType()),
        StructField("price", StringType()),
        StructField("quantity", StringType()),
    ])

    raw = spark.read.csv(csv_path, header=True, schema=schema)

    with_meta = (raw
        .withColumn("_ingested_at", f.current_timestamp())
        .withColumn("_source_file", f.input_file_name())
    )

    deduped = with_meta.dropDuplicates(["order_id"])

    return deduped


# ---- Test harness ----
if __name__ == "__main__":
    import tempfile, os

    spark = SparkSession.builder.appName("BronzeTest").master("local[*]").getOrCreate()

    tmp = tempfile.mkdtemp()
    csv_path = os.path.join(tmp, "orders.csv")
    with open(csv_path, "w") as fh:
        fh.write("order_id,product,price,quantity\n")
        fh.write("1,widget,9.99,2\n")
        fh.write("2,gadget,24.99,1\n")
        fh.write("1,widget,9.99,2\n")

    df = bronze_orders(spark, csv_path)
    assert df.count() == 2, f"Expected 2 rows after dedup, got {df.count()}"
    assert "_ingested_at" in df.columns, "Missing _ingested_at column"
    assert "_source_file" in df.columns, "Missing _source_file column"
    assert df.schema["price"].dataType == StringType(), "price should be StringType"
    print("All tests passed!")
    df.show(truncate=False)
    spark.stop()
