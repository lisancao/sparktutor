"""
Gold Layer - Starter Code

Implement `gold_product_summary` that:
1. Reads from the 'silver_orders' temp view
2. Groups by `product`
3. Computes: order_count, total_revenue, avg_order_value
4. Adds a `revenue_rank` column (rank by total_revenue descending)

Expected output columns:
  product, order_count, total_revenue, avg_order_value, revenue_rank
"""

from pyspark.sql import SparkSession, functions as f, Window


def gold_product_summary(spark):
    """Produce a gold-level product summary with rankings."""

    silver = spark.table("silver_orders")

    # TODO: Group by product and compute aggregations
    agg_df = silver  # Replace

    # TODO: Add revenue_rank using a window function
    #       Rank 1 = highest total_revenue
    ranked = agg_df  # Replace

    return ranked


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("GoldTest").master("local[*]").getOrCreate()

    # Create silver test data
    data = [
        ("1", "widget", 9.99, 2, 19.98, 14),
        ("2", "gadget", 24.99, 1, 24.99, 9),
        ("3", "widget", 9.99, 5, 49.95, 16),
        ("4", "gizmo", 4.99, 10, 49.90, 11),
    ]
    silver = spark.createDataFrame(
        data, ["order_id", "product", "price", "quantity", "total", "order_hour"]
    )
    silver.createOrReplaceTempView("silver_orders")

    df = gold_product_summary(spark)

    assert df.count() == 3, f"Expected 3 products, got {df.count()}"
    assert "revenue_rank" in df.columns, "Missing 'revenue_rank' column"
    assert "total_revenue" in df.columns, "Missing 'total_revenue' column"

    top = df.filter(f.col("revenue_rank") == 1).first()
    assert top["product"] == "widget", f"Expected widget as #1, got {top['product']}"

    print("All tests passed!")
    df.show(truncate=False)
    spark.stop()
