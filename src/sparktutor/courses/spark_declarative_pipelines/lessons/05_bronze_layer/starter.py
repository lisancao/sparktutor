"""
Bronze Layer - Starter Code

Implement the `bronze_orders` function that:
1. Reads CSV from `csv_path` using an all-StringType schema
2. Adds `_ingested_at` column (current_timestamp)
3. Adds `_source_file` column (input_file_name)
4. Deduplicates by `order_id`

Expected schema of the returned DataFrame:
  order_id: string
  product: string
  price: string       (kept as string for schema-on-read)
  quantity: string     (kept as string for schema-on-read)
  _ingested_at: timestamp
  _source_file: string
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType


def bronze_orders(spark, csv_path):
    """Ingest raw orders CSV into a bronze DataFrame."""

    # TODO: Define an all-StringType schema with columns:
    #       order_id, product, price, quantity
    schema = None  # Replace with StructType(...)

    # TODO: Read the CSV with the schema above (header=True)
    raw = None  # Replace with spark.read...

    # TODO: Add _ingested_at and _source_file columns
    with_meta = None  # Replace

    # TODO: Deduplicate by order_id
    deduped = None  # Replace

    return deduped


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    import tempfile, os

    spark = SparkSession.builder.appName("BronzeTest").master("local[*]").getOrCreate()

    # Create test CSV
    tmp = tempfile.mkdtemp()
    csv_path = os.path.join(tmp, "orders.csv")
    with open(csv_path, "w") as fh:
        fh.write("order_id,product,price,quantity\n")
        fh.write("1,widget,9.99,2\n")
        fh.write("2,gadget,24.99,1\n")
        fh.write("1,widget,9.99,2\n")  # duplicate

    df = bronze_orders(spark, csv_path)
    assert df.count() == 2, f"Expected 2 rows after dedup, got {df.count()}"
    assert "_ingested_at" in df.columns, "Missing _ingested_at column"
    assert "_source_file" in df.columns, "Missing _source_file column"
    assert df.schema["price"].dataType == StringType(), "price should be StringType"
    print("All tests passed!")
    spark.stop()
