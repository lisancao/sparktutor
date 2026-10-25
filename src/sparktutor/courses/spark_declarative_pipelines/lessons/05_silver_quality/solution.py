"""
Lesson 5: Silver and Quarantine (solution)
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


# ---- Silver ----
ORDER_COLUMNS = ["order_id", "customer_id", "product_id", "quantity", "unit_price", "status", "order_ts"]


@dp.materialized_view(comment="Typed customer dimension", table_properties={"quality": "silver"})
def silver_customers() -> DataFrame:
    return spark.table("bronze_customers").select(
        "customer_id", "name", "email", "city", F.to_date("signup_date").alias("signup_date")
    )


@dp.temporary_view
def orders_typed() -> DataFrame:
    latest_first = Window.partitionBy("order_id").orderBy(F.col("_ingested_at").desc())
    return (
        spark.table("bronze_orders")
        .withColumn("_rn", F.row_number().over(latest_first))
        .where("_rn = 1")
        .select(
            "order_id", "customer_id", "product_id", "quantity", "status",
            F.col("unit_price").try_cast("decimal(10,2)").alias("unit_price"),
            F.try_to_timestamp("order_ts").alias("order_ts"),
        )
    )


@dp.temporary_view
def orders_checked() -> DataFrame:
    known = spark.table("silver_customers").select("customer_id", "city")
    return (
        spark.table("orders_typed")
        .join(known, "customer_id", "left")
        .withColumn(
            "_reason",
            F.when(F.col("unit_price").isNull(), "invalid_price")
            .when(F.col("quantity") <= 0, "invalid_quantity")
            .when(F.col("city").isNull(), "unknown_customer"),
        )
    )


@dp.materialized_view(comment="Valid, deduplicated orders", table_properties={"quality": "silver"})
def silver_orders() -> DataFrame:
    return (
        spark.table("orders_checked")
        .where("_reason IS NULL")
        .select(*ORDER_COLUMNS, "city", (F.col("quantity") * F.col("unit_price")).alias("line_total"))
    )


@dp.materialized_view(comment="Orders that failed validation, with the reason")
def quarantine_orders() -> DataFrame:
    return spark.table("orders_checked").where("_reason IS NOT NULL").select(*ORDER_COLUMNS, "_reason")


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
