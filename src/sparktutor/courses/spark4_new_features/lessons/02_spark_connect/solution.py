"""
Spark Connect — Refactor Pipeline for Connect Compatible Code

Refactored order filtering using only DataFrame API.
"""

from pyspark.sql import SparkSession, functions as f

ORDERS_DATA = [
    ("o1", "pending", 99.99),
    ("o2", "shipped", 149.50),
    ("o3", "pending", 25.00),
    ("o4", "delivered", 299.00),
    ("o5", "pending", 45.50),
]
ORDERS_COLUMNS = ["order_id", "status", "total"]

def create_session(use_connect: bool, url: str = "sc://localhost:15002"):
    """Create SparkSession — remote if use_connect else local."""
    builder = SparkSession.builder.appName("ECommerce")
    if use_connect:
        return builder.remote(url).getOrCreate()
    return builder.master("local[*]").getOrCreate()


def filter_orders_by_status(spark, status: str):
    """
    Load orders and filter by status using DataFrame API only.
    Must work over Spark Connect (no RDD, no sparkContext).
    Returns DataFrame of orders with given status.
    """
    orders_df = spark.createDataFrame(ORDERS_DATA, ORDERS_COLUMNS)
    return orders_df.filter(f.col("status") == status)


# ---- Test harness ----
if __name__ == "__main__":
    spark = create_session(use_connect=False)
    result = filter_orders_by_status(spark, "pending")
    assert result is not None, "Function returned None"
    rows = result.collect()
    assert len(rows) == 3, f"Expected 3 pending orders, got {len(rows)}"
    statuses = [r.status for r in rows]
    assert all(s == "pending" for s in statuses), f"Expected all pending, got {statuses}"
    assert "order_id" in result.columns and "total" in result.columns
    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
