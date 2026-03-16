"""
New Python DataFrame API — Product Analytics with transform()

Implement add_revenue and top_products_by_revenue using .transform() composition.
"""

from pyspark.sql import SparkSession, DataFrame, functions as f

LINE_ITEMS_DATA = [
    ("o1", "p1", 2, 29.99),
    ("o1", "p2", 1, 49.99),
    ("o2", "p1", 3, 29.99),
    ("o2", "p3", 1, 99.99),
    ("o3", "p2", 2, 49.99),
]
LINE_ITEMS_COLUMNS = ["order_id", "product_id", "quantity", "price"]


def add_revenue(df: DataFrame) -> DataFrame:
    """
    Add column revenue = quantity * price.
    """
    # TODO: withColumn("revenue", quantity * price)
    pass


def top_products_by_revenue(df: DataFrame, n: int) -> DataFrame:
    """
    Group by product_id, sum revenue, order by total revenue desc, limit n.
    """
    # TODO: groupBy product_id, agg sum(revenue), orderBy desc, limit n
    pass


def product_analytics_pipeline(spark):
    """
    Build line items DataFrame, add revenue, return top 3 products by revenue.
    Use .transform() to compose add_revenue and top_products_by_revenue.
    """
    df = spark.createDataFrame(LINE_ITEMS_DATA, LINE_ITEMS_COLUMNS)
    # TODO: df.transform(add_revenue).transform(lambda d: top_products_by_revenue(d, 3))
    pass


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("ProductAnalytics").master("local[*]").getOrCreate()
    result = product_analytics_pipeline(spark)
    assert result is not None, "Function returned None"
    rows = result.collect()
    assert len(rows) <= 3, f"Expected at most 3 rows, got {len(rows)}"
    assert "product_id" in result.columns
    assert "revenue" in result.columns or any("sum" in c.lower() for c in result.columns)
    totals = [r[1] if len(r) == 2 else getattr(r, "sum(revenue)", getattr(r, "total_revenue", 0)) for r in rows]
    if len(totals) >= 2:
        assert totals[0] >= totals[1], "Expected descending order by revenue"
    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
