"""
Migration Capstone — Full E-Commerce Pipeline

Complete Spark 4 native pipeline wiring orders, line items, and products.
"""

from pyspark.sql import SparkSession, DataFrame, functions as f

ORDERS_DATA = [("o1", "shipped", 99.99), ("o2", "pending", 149.50)]
ORDERS_COLUMNS = ["order_id", "status", "total"]

LINES_DATA = [
    ("o1", "p1", 2, 29.99),
    ("o1", "p2", 1, 49.99),
    ("o2", "p1", 3, 29.99),
]
LINES_COLUMNS = ["order_id", "product_id", "quantity", "price"]

PRODUCTS_DATA = [
    ("p1", "Widget", "Electronics"),
    ("p2", "Gadget", "Electronics"),
]


def full_ecommerce_pipeline(spark) -> DataFrame:
    """
    Full pipeline: load, join, add revenue (ANSI-safe), aggregate by product and category.
    """
    orders = spark.createDataFrame(ORDERS_DATA, ORDERS_COLUMNS)
    lines = spark.createDataFrame(LINES_DATA, LINES_COLUMNS)
    products = spark.createDataFrame(PRODUCTS_DATA, ["product_id", "name", "category"])

    enriched = (
        lines
        .join(orders, "order_id")
        .join(products, "product_id")
        .withColumn("revenue", f.try_multiply(f.col("quantity"), f.col("price")))
    )

    return (
        enriched
        .groupBy("product_id", "category")
        .agg(f.sum("revenue").alias("total_revenue"))
    )


# ---- Test harness ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("Capstone").master("local[*]").getOrCreate()
    result = full_ecommerce_pipeline(spark)
    assert result is not None, "Function returned None"
    rows = result.collect()
    assert len(rows) >= 2, f"Expected at least 2 rows, got {len(rows)}"
    assert "product_id" in result.columns and "category" in result.columns
    assert "total_revenue" in result.columns
    total_rev = sum(float(r.total_revenue) for r in rows)
    assert total_rev > 150, f"Expected total revenue > 150, got {total_rev}"
    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
