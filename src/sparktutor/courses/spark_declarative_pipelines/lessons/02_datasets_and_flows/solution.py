"""
Lesson 2: A Declared Table, a Flow and Two Readers (solution)

Graph to build:
  orders_raw        streaming table, declared with dp.create_streaming_table
  ingest_orders     append flow into orders_raw (every file in data/orders)
  placed_orders     temporary view: orders_raw rows with status = 'placed'
  orders_by_status  materialized view: status, order_count
"""

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

spark: SparkSession

ORDER_SCHEMA = (
    "order_id STRING, customer_id STRING, product_id STRING, quantity INT, "
    "unit_price STRING, status STRING, order_ts STRING"
)

dp.create_streaming_table("orders_raw", comment="Every order event")


@dp.append_flow(target="orders_raw")
def ingest_orders() -> DataFrame:
    return spark.readStream.schema(ORDER_SCHEMA).json("data/orders")


@dp.temporary_view
def placed_orders() -> DataFrame:
    return spark.table("orders_raw").where(F.col("status") == "placed")


@dp.materialized_view
def orders_by_status() -> DataFrame:
    return spark.table("orders_raw").groupBy("status").agg(F.count("*").alias("order_count"))


# ---- Checks (do not modify below this line) ----
@dp.materialized_view
def check_orders_raw() -> DataFrame:
    return spark.table("orders_raw").agg(F.count("*").alias("n")).select(
        F.assert_true(
            F.col("n") == 11,
            F.format_string("orders_raw: expected 11 rows, got %d", F.col("n")),
        ).alias("ok")
    )


@dp.materialized_view
def check_placed_orders() -> DataFrame:
    return spark.table("placed_orders").agg(F.count("*").alias("n")).select(
        F.assert_true(
            F.col("n") == 8,
            F.format_string("placed_orders: expected 8 rows, got %d", F.col("n")),
        ).alias("ok")
    )


@dp.materialized_view
def check_orders_by_status() -> DataFrame:
    expected = (
        ((F.col("status") == "placed") & (F.col("order_count") == 8))
        | ((F.col("status") == "shipped") & (F.col("order_count") == 2))
        | ((F.col("status") == "cancelled") & (F.col("order_count") == 1))
    )
    return spark.table("orders_by_status").agg(F.count_if(expected).alias("n")).select(
        F.assert_true(
            F.col("n") == 3,
            "orders_by_status: expected placed=8, shipped=2, cancelled=1",
        ).alias("ok")
    )
