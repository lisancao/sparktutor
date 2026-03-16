"""
ANSI Mode & SQL Compliance — Fix Pipeline That Breaks Under ANSI

Uses try_divide and try_multiply for ANSI-safe aggregations.
"""

from pyspark.sql import SparkSession, DataFrame, functions as f

ORDERS_DATA = [
    ("o1", "p1", 2, 29.99),
    ("o2", "p2", 0, 49.99),
    ("o3", "p1", 1, 29.99),
]
ORDERS_COLUMNS = ["order_id", "product_id", "quantity", "price"]


def fix_ansi_safe_aggregates(spark) -> DataFrame:
    """
    Build orders DataFrame, add line_total = quantity * price using try_multiply,
    then aggregate: sum(line_total), count(*), and avg_order = sum/count using try_divide.
    Return DataFrame with product_id, total_revenue, order_count, avg_order.
    """
    df = spark.createDataFrame(ORDERS_DATA, ORDERS_COLUMNS)
    df = df.withColumn("line_total", f.try_multiply(f.col("price"), f.col("quantity")))
    agg_df = (
        df.groupBy("product_id")
        .agg(
            f.sum("line_total").alias("total_revenue"),
            f.count("*").alias("order_count"),
        )
    )
    return agg_df.withColumn(
        "avg_order",
        f.coalesce(f.try_divide(f.col("total_revenue"), f.col("order_count")), f.lit(0.0)),
    )


# ---- Test harness ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("ANSISafe").master("local[*]").getOrCreate()
    result = fix_ansi_safe_aggregates(spark)
    assert result is not None, "Function returned None"
    rows = result.collect()
    assert len(rows) >= 1, f"Expected at least 1 row, got {len(rows)}"
    assert "product_id" in result.columns
    assert "total_revenue" in result.columns
    assert "order_count" in result.columns
    p2_row = next((r for r in rows if r.product_id == "p2"), None)
    if p2_row:
        assert p2_row.order_count == 1, f"p2 should have 1 order, got {p2_row.order_count}"
    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
