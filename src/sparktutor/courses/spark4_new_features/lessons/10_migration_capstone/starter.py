"""
Migration Capstone — Full E-Commerce Pipeline

Wire together orders, line items, and products into a Spark 4 native pipeline.
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
    Full pipeline:
    1. Load orders, line items, products
    2. Join lines with orders and products
    3. Add revenue = quantity * price (use try_multiply for ANSI safety)
    4. Aggregate total revenue by product_id and category
    Returns DataFrame: product_id, category, total_revenue
    """
    # TODO: Create DataFrames from ORDERS_DATA, LINES_DATA, PRODUCTS_DATA
    # TODO: Join lines -> orders (order_id), lines -> products (product_id)
    # TODO: withColumn revenue = try_multiply(quantity, price)
    # TODO: groupBy product_id, category; agg sum(revenue) as total_revenue
    pass


# ---- Test harness (do not modify below this line) ----
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
