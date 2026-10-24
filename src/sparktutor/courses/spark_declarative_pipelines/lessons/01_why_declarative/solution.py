"""
Lesson 1: Two Materialized Views (solution)
"""

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

spark: SparkSession

PRODUCT_SCHEMA = "product_id STRING, name STRING, category STRING, list_price DECIMAL(10,2)"


@dp.materialized_view
def products() -> DataFrame:
    return spark.read.option("header", True).schema(PRODUCT_SCHEMA).csv("data/products.csv")


@dp.materialized_view
def products_by_category() -> DataFrame:
    return (
        spark.table("products")
        .groupBy("category")
        .agg(
            F.count("*").alias("product_count"),
            F.avg("list_price").alias("avg_list_price"),
        )
    )


# ---- Checks (do not modify below this line) ----
@dp.materialized_view
def check_products_by_category() -> DataFrame:
    merch_ok = (
        (F.col("category") == "merch")
        & (F.col("product_count") == 2)
        & (F.round("avg_list_price", 3) == 61.625)
    )
    return spark.table("products_by_category").agg(
        F.count("*").alias("rows"), F.count_if(merch_ok).alias("merch_ok")
    ).select(
        F.assert_true(
            (F.col("rows") == 2) & (F.col("merch_ok") == 1),
            "products_by_category: expected 2 categories, and merch with product_count 2 "
            "and avg_list_price 61.625",
        ).alias("ok")
    )
