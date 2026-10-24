"""
Lesson 4: The Bronze Layer

Define:
  bronze_orders            streaming table over data/orders + lineage columns
  bronze_customer_changes  streaming table over data/customer_changes + lineage columns
  bronze_customers         materialized view over data/customers.csv + _ingested_at

Bronze keeps everything that arrived: no filters, no dedup.
"""

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

spark: SparkSession

ORDER_SCHEMA = (
    "order_id STRING, customer_id STRING, product_id STRING, quantity INT, "
    "unit_price STRING, status STRING, order_ts STRING"
)
CHANGE_SCHEMA = "customer_id STRING, name STRING, city STRING, op STRING, seq INT"
CUSTOMER_SCHEMA = "customer_id STRING, name STRING, email STRING, city STRING, signup_date STRING"


# TODO: @dp.table with a comment and table_properties={"quality": "bronze"}
def bronze_orders() -> DataFrame:
    # TODO: stream data/orders with ORDER_SCHEMA
    # TODO: add _source_file (from _metadata.file_name) and _ingested_at
    pass


# TODO: @dp.table
def bronze_customer_changes() -> DataFrame:
    # TODO: stream data/customer_changes with CHANGE_SCHEMA, plus the lineage columns
    pass


# TODO: @dp.materialized_view
def bronze_customers() -> DataFrame:
    # TODO: read data/customers.csv (header) with CUSTOMER_SCHEMA, plus _ingested_at
    pass


# ---- Checks (do not modify below this line) ----
def _expect(table: str, condition: str, message: str) -> DataFrame:
    df = spark.table(table)
    return df.agg(F.expr(condition).alias("ok")).select(
        F.assert_true(F.col("ok"), f"{table}: {message}").alias("ok")
    )


@dp.materialized_view
def check_bronze_orders() -> DataFrame:
    return _expect(
        "bronze_orders",
        "count(*) = 11 AND count(DISTINCT _source_file) = 2 AND count(_ingested_at) = 11",
        "expected all 11 raw rows (duplicates included) from 2 files, with lineage columns",
    )


@dp.materialized_view
def check_bronze_customer_changes() -> DataFrame:
    return _expect(
        "bronze_customer_changes",
        "count(*) = 6 AND max(_source_file) = 'changes_001.json'",
        "expected 6 change events with _source_file",
    )


@dp.materialized_view
def check_bronze_customers() -> DataFrame:
    return _expect(
        "bronze_customers",
        "count(*) = 5 AND count(_ingested_at) = 5",
        "expected 5 customers with _ingested_at",
    )
