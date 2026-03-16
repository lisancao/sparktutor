"""
Structured Streaming in Spark 4 — Migrate Streaming Aggregation

Simulate streaming micro-batches: union batches and aggregate revenue by product.
"""

from pyspark.sql import SparkSession, DataFrame, functions as f

BATCH1 = [("o1", "p1", 29.99), ("o1", "p2", 49.99), ("o2", "p1", 29.99)]
BATCH2 = [("o3", "p2", 49.99), ("o4", "p1", 59.98)]
BATCH3 = [("o5", "p3", 19.99), ("o5", "p1", 29.99)]
COLUMNS = ["order_id", "product_id", "revenue"]


def streaming_revenue_by_product(spark, batches: list) -> DataFrame:
    """
    Simulate streaming: take a list of batch DataFrames (each with order_id,
    product_id, revenue), union them, and aggregate sum(revenue) by product_id.
    Returns DataFrame: product_id, total_revenue.
    """
    # TODO: Create DataFrame from each batch, union all, groupBy product_id, agg sum(revenue)
    pass


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("Streaming").master("local[*]").getOrCreate()
    batch_dfs = [
        spark.createDataFrame(BATCH1, COLUMNS),
        spark.createDataFrame(BATCH2, COLUMNS),
        spark.createDataFrame(BATCH3, COLUMNS),
    ]
    result = streaming_revenue_by_product(spark, batch_dfs)
    assert result is not None, "Function returned None"
    rows = result.collect()
    assert len(rows) >= 2, f"Expected at least 2 products, got {len(rows)}"
    p1_total = next((r.total_revenue for r in rows if r.product_id == "p1"), None)
    assert p1_total is not None, "Expected product p1"
    assert float(p1_total) > 100, f"p1 revenue should exceed 100, got {p1_total}"
    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
