# spark-pipelines: dry-run
"""
Lesson 3: Make the Dry Run Pass

This pipeline has three bugs. Submit it, read the dry-run error, fix it,
repeat. Keep every dataset.
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
CUSTOMER_SCHEMA = "customer_id STRING, name STRING, email STRING, city STRING, signup_date DATE"


@dp.table
def orders_bronze() -> DataFrame:
    return spark.readStream.schema(ORDER_SCHEMA).json("data/orders")


@dp.materialized_view
def customers() -> DataFrame:
    return spark.read.option("header", True).schema(CUSTOMER_SCHEMA).csv("data/customers.csv")


@dp.materialized_view
def orders_enriched() -> DataFrame:
    return (
        spark.table("orders_bronz")
        .join(spark.table("customers"), "customer_id")
        .withColumn("line_total", F.col("quantity") * F.expr("try_cast(unit_price AS DECIMAL(10,2))"))
    )


@dp.materialized_view
def revenue_by_city() -> DataFrame:
    return spark.table("orders_enriched").groupBy("region").agg(F.sum("line_total").alias("revenue"))


@dp.materialized_view
def revenue_by_customer() -> DataFrame:
    return spark.table("top_customers").groupBy("customer_id", "name").agg(
        F.sum("line_total").alias("revenue")
    )


@dp.materialized_view
def top_customers() -> DataFrame:
    w = Window.orderBy(F.col("revenue").desc())
    return spark.table("revenue_by_customer").withColumn("rank", F.rank().over(w))
