"""
Gold Layer - Solution

Product-level aggregation with revenue ranking.
"""

from pyspark.sql import SparkSession, functions as f, Window


def gold_product_summary(spark):
    """Produce a gold-level product summary with rankings."""

    silver = spark.table("silver_orders")

    # Aggregate by product
    agg_df = (silver
        .groupBy("product")
        .agg(
            f.count("*").alias("order_count"),
            f.sum("total").alias("total_revenue"),
            f.avg("total").alias("avg_order_value"),
        )
    )

    # Rank products by revenue (highest first)
    w = Window.orderBy(f.col("total_revenue").desc())
    ranked = agg_df.withColumn("revenue_rank", f.rank().over(w))

    return ranked


# ---- Test harness ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("GoldTest").master("local[*]").getOrCreate()

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
