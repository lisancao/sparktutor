"""
Lesson 6: Gold Aggregates (solution)
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
PRODUCT_SCHEMA = "product_id STRING, name STRING, category STRING, list_price DECIMAL(10,2)"


# ---- Bronze and silver (from lessons 4 and 5; read-only) ----
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
            F.to_timestamp("order_ts").alias("order_ts"),
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


@dp.materialized_view(comment="Product dimension", table_properties={"quality": "silver"})
def silver_products() -> DataFrame:
    return spark.read.option("header", True).schema(PRODUCT_SCHEMA).csv("data/products.csv")


# ---- Gold ----
CATEGORIES = ["hardware", "merch"]


@dp.temporary_view
def billable_orders() -> DataFrame:
    """Silver orders that count toward revenue."""
    return spark.table("silver_orders").where("status <> 'cancelled'")


@dp.materialized_view(comment="Revenue per day with a running total", table_properties={"quality": "gold"})
def gold_daily_revenue() -> DataFrame:
    running = Window.orderBy("order_date").rowsBetween(Window.unboundedPreceding, Window.currentRow)
    return (
        spark.table("billable_orders")
        .groupBy(F.to_date("order_ts").alias("order_date"))
        .agg(
            F.sum("line_total").alias("revenue"),
            F.count("*").alias("order_count"),
            F.round(F.avg("line_total"), 2).alias("avg_order_value"),
        )
        .withColumn("cumulative_revenue", F.sum("revenue").over(running))
    )


@dp.materialized_view(comment="Revenue per customer, ranked", table_properties={"quality": "gold"})
def gold_customer_value() -> DataFrame:
    by_revenue = Window.orderBy(F.col("revenue").desc())
    everyone = Window.partitionBy()
    return (
        spark.table("billable_orders")
        .groupBy("customer_id", "city")
        .agg(F.sum("line_total").alias("revenue"), F.count("*").alias("order_count"))
        .withColumn("revenue_rank", F.dense_rank().over(by_revenue))
        .withColumn("revenue_share", F.col("revenue") / F.sum("revenue").over(everyone))
    )


for category in CATEGORIES:

    @dp.materialized_view(name=f"gold_revenue_{category}", table_properties={"quality": "gold"})
    def revenue_for_category(category: str = category) -> DataFrame:
        products = spark.table("silver_products").where(F.col("category") == category)
        return (
            spark.table("billable_orders")
            .join(products.select("product_id", F.col("name").alias("product_name")), "product_id")
            .groupBy("product_id", "product_name")
            .agg(F.sum("line_total").alias("revenue"))
        )


# ---- Checks (do not modify below this line) ----
def _expect(table: str, condition: str, message: str) -> DataFrame:
    return spark.table(table).agg(F.expr(condition).alias("ok")).select(
        F.assert_true(F.col("ok"), f"{table}: {message}").alias("ok")
    )


@dp.materialized_view
def check_gold_daily_revenue() -> DataFrame:
    return _expect(
        "gold_daily_revenue",
        "count(*) = 2 "
        "AND max_by(revenue, order_date) = 133.00 AND min_by(revenue, order_date) = 214.43 "
        "AND max(cumulative_revenue) = 347.43 AND sum(order_count) = 6",
        "expected 2026-10-01 = 214.43 (4 orders), 2026-10-02 = 133.00 (2 orders), "
        "cumulative_revenue ending at 347.43; cancelled orders excluded",
    )


@dp.materialized_view
def check_gold_customer_value() -> DataFrame:
    return _expect(
        "gold_customer_value",
        "count(*) = 4 AND max_by(customer_id, -revenue_rank) = 'c-02' "
        "AND min_by(customer_id, -revenue_rank) = 'c-05' "
        "AND round(sum(revenue_share), 6) = 1.0",
        "expected 4 customers ranked c-02 first and c-05 last, revenue_share summing to 1",
    )


@dp.materialized_view
def check_gold_category_tables() -> DataFrame:
    hardware = spark.table("gold_revenue_hardware").agg(F.sum("revenue").alias("hardware"))
    merch = spark.table("gold_revenue_merch").agg(F.sum("revenue").alias("merch"))
    return hardware.crossJoin(merch).select(
        F.assert_true(
            (F.col("hardware") == 94.43) & (F.col("merch") == 253.00),
            "gold_revenue_<category>: expected hardware 94.43 and merch 253.00",
        ).alias("ok")
    )
