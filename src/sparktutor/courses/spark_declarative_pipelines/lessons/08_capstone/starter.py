"""
Capstone: Raw Files to Gold

Build the whole retail pipeline in one file, from memory where you can:

  bronze   bronze_orders (streaming), bronze_customers (MV)
  silver   silver_customers, silver_products, orders_typed (temp view),
           orders_checked (temp view), silver_orders, quarantine_orders
  gold     billable_orders (temp view), gold_daily_revenue, gold_customer_value,
           gold_revenue_<category> for each of CATEGORIES
  sink     shipping_feed (JSON files in exports/shipping_feed) fed by
           shipped_orders_to_feed with every shipped order from bronze

The checks at the bottom reconcile the layers with each other.
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


CATEGORIES = ["hardware", "merch"]
ORDER_COLUMNS = ["order_id", "customer_id", "product_id", "quantity", "unit_price", "status", "order_ts"]


# ---- Bronze ----
# TODO: bronze_orders: streaming table over data/orders with _source_file and _ingested_at
# TODO: bronze_customers: materialized view over data/customers.csv with _ingested_at


# ---- Silver ----
# TODO: silver_customers (signup_date as DATE) and silver_products (data/products.csv)
# TODO: orders_typed: dedupe on order_id with row_number(), try_cast unit_price, to_timestamp order_ts
# TODO: orders_checked: add city and _reason (invalid_price, invalid_quantity, unknown_customer)
# TODO: silver_orders (no _reason, plus line_total) and quarantine_orders (with _reason)


# ---- Gold ----
# TODO: billable_orders: silver_orders without cancelled orders
# TODO: gold_daily_revenue: order_date, revenue, order_count, avg_order_value, cumulative_revenue
# TODO: gold_customer_value: customer_id, city, revenue, order_count, revenue_rank, revenue_share
# TODO: gold_revenue_<category> for each category in CATEGORIES


# ---- Sink ----
# TODO: dp.create_sink("shipping_feed", format="json", options={"path": "exports/shipping_feed"})
# TODO: an append flow shipped_orders_to_feed that streams shipped orders from bronze_orders


# ---- Checks (do not modify below this line) ----
def _expect(df: DataFrame, condition: str, message: str) -> DataFrame:
    return df.agg(F.expr(condition).alias("ok")).select(F.assert_true(F.col("ok"), message).alias("ok"))


@dp.materialized_view
def check_every_order_accounted_for() -> DataFrame:
    unique_bronze = spark.table("bronze_orders").agg(F.countDistinct("order_id").alias("bronze"))
    silver = spark.table("silver_orders").agg(F.count("*").alias("silver"))
    quarantined = spark.table("quarantine_orders").agg(F.count("*").alias("quarantined"))
    return _expect(
        unique_bronze.crossJoin(silver).crossJoin(quarantined),
        "first(bronze) = 10 AND first(silver) + first(quarantined) = first(bronze) AND first(quarantined) = 3",
        "every unique bronze order must land in exactly one of silver_orders or quarantine_orders "
        "(expected 10 = 7 + 3)",
    )


@dp.materialized_view
def check_gold_reconciles_with_silver() -> DataFrame:
    billable = spark.table("silver_orders").where("status <> 'cancelled'").agg(
        F.sum("line_total").alias("silver_revenue")
    )
    daily = spark.table("gold_daily_revenue").agg(F.sum("revenue").alias("daily_revenue"))
    customers = spark.table("gold_customer_value").agg(F.sum("revenue").alias("customer_revenue"))
    return _expect(
        billable.crossJoin(daily).crossJoin(customers),
        "first(silver_revenue) = 347.43 AND first(daily_revenue) = first(silver_revenue) "
        "AND first(customer_revenue) = first(silver_revenue)",
        "gold_daily_revenue and gold_customer_value must both add up to billable silver revenue (347.43)",
    )
