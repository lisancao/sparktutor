"""
Lesson 1: Two Materialized Views

Define:
  products              - data/products.csv with an explicit schema
  products_by_category  - one row per category with product_count and avg_list_price

This file is run with `spark-pipelines run`, so `spark` is injected for you.
"""

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

spark: SparkSession

PRODUCT_SCHEMA = "product_id STRING, name STRING, category STRING, list_price DECIMAL(10,2)"


# TODO: decorate with @dp.materialized_view
def products() -> DataFrame:
    # TODO: read data/products.csv with header=True and PRODUCT_SCHEMA
    pass


# TODO: decorate with @dp.materialized_view
def products_by_category() -> DataFrame:
    # TODO: read the products dataset with spark.table("products"),
    #       group by category and compute product_count and avg_list_price
    pass


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
