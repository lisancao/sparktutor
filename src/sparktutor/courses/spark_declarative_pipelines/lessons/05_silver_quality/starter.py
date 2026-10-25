"""
Lesson 5: Silver and Quarantine

Add silver_customers, orders_typed, orders_checked, silver_orders and
quarantine_orders below the bronze layer. Every deduplicated bronze order
must end up in exactly one of silver_orders or quarantine_orders.
"""

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

spark: SparkSession

ORDER_SCHEMA = (
    "order_id STRING, customer_id STRING, product_id STRING, quantity INT, "
    "unit_price STRING, status STRING, order_ts STRING"
)
CUSTOMER_SCHEMA = "customer_id STRING, name STRING, email STRING, city STRING, signup_date STRING"


# ---- Bronze (from lesson 4) ----
@dp.table(comment="Raw order events as received", table_properties={"quality": "bronze"})
def bronze_orders() -> DataFrame:
    return (
        spark.readStream.schema(ORDER_SCHEMA).json("data/orders")
        .withColumn("_source_file", F.col("_metadata.file_name"))
        .withColumn("_ingested_at", F.current_timestamp())
    )


@dp.materialized_view(comment="Customer snapshot as received", table_properties={"quality": "bronze"})
def bronze_customers() -> DataFrame:
    return (
        spark.read.option("header", True).schema(CUSTOMER_SCHEMA).csv("data/customers.csv")
        .withColumn("_ingested_at", F.current_timestamp())
    )


# ---- Silver (your code) ----
# TODO: @dp.materialized_view
def silver_customers() -> DataFrame:
    # TODO: bronze_customers with signup_date cast to DATE;
    #       select customer_id, name, email, city, signup_date
    pass


# TODO: @dp.temporary_view
def orders_typed() -> DataFrame:
    # TODO: one row per order_id (latest _ingested_at wins) using row_number() over a window,
    #       unit_price via try_cast to DECIMAL(10,2), order_ts via try_to_timestamp.
    #       Use an explicit select, not .drop() or .dropDuplicates([...]).
    pass


# TODO: @dp.temporary_view
def orders_checked() -> DataFrame:
    # TODO: left join silver_customers to find unknown customers and add _reason:
    #       invalid_price (unit_price is NULL), invalid_quantity (quantity <= 0),
    #       unknown_customer (no matching customer), else NULL. Keep city.
    pass


# TODO: @dp.materialized_view
def silver_orders() -> DataFrame:
    # TODO: rows without a _reason, plus line_total = quantity * unit_price
    pass


# TODO: @dp.materialized_view
def quarantine_orders() -> DataFrame:
    # TODO: rows with a _reason
    pass


# ---- Checks (do not modify below this line) ----
def _expect(table: str, condition: str, message: str) -> DataFrame:
    return spark.table(table).agg(F.expr(condition).alias("ok")).select(
        F.assert_true(F.col("ok"), f"{table}: {message}").alias("ok")
    )


@dp.materialized_view
def check_silver_customers() -> DataFrame:
    return _expect(
        "silver_customers",
        "count(*) = 5 AND typeof(max(signup_date)) = 'date'",
        "expected 5 customers with signup_date as DATE",
    )


@dp.materialized_view
def check_silver_orders() -> DataFrame:
    return _expect(
        "silver_orders",
        "count(*) = 7 AND count(DISTINCT order_id) = 7 AND typeof(max(unit_price)) = 'decimal(10,2)' "
        "AND count(city) = 7 AND sum(line_total) = 367.41",
        "expected 7 unique valid orders (cancelled included) with city, decimal unit_price "
        "and line_total summing to 367.41",
    )


@dp.materialized_view
def check_quarantine_orders() -> DataFrame:
    return _expect(
        "quarantine_orders",
        "count(*) = 3 AND count_if(_reason = 'invalid_price') = 1 "
        "AND count_if(_reason = 'invalid_quantity') = 1 AND count_if(_reason = 'unknown_customer') = 1",
        "expected one row each for invalid_price, invalid_quantity and unknown_customer",
    )
