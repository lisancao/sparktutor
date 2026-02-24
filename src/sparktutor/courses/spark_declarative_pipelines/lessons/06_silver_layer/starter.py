"""
Silver Layer - Starter Code

Implement `silver_orders` that:
1. Reads from the 'bronze_orders' temp view
2. Casts `price` to double and `quantity` to int
3. Adds a `total` column (price * quantity)
4. Filters out rows where price is null (bad data)
5. Adds an `order_hour` column: the hour extracted from `order_ts`

Expected output columns:
  order_id, product, price (double), quantity (int), order_ts (string),
  _ingested_at, total (double), order_hour (int)
"""

from pyspark.sql import SparkSession, functions as f


def silver_orders(spark):
    """Transform bronze_orders into a clean silver DataFrame."""

    bronze = spark.table("bronze_orders")

    # TODO: Cast price to double and quantity to int
    typed = bronze  # Replace

    # TODO: Add 'total' column = price * quantity
    with_total = typed  # Replace

    # TODO: Filter out rows where price is null
    clean = with_total  # Replace

    # TODO: Add 'order_hour' = hour extracted from order_ts
    #       (order_ts is a string like '2026-01-15 14:30:00')
    enriched = clean  # Replace

    return enriched


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("SilverTest").master("local[*]").getOrCreate()

    # Create bronze test data
    data = [
        ("1", "widget", "9.99", "2", "2026-01-15 14:30:00"),
        ("2", "gadget", "24.99", "1", "2026-01-15 09:15:00"),
        ("3", "doohickey", "N/A", "3", "2026-01-15 22:00:00"),  # bad price
    ]
    bronze = spark.createDataFrame(data, ["order_id", "product", "price", "quantity", "order_ts"])
    bronze = bronze.withColumn("_ingested_at", f.current_timestamp())
    bronze.createOrReplaceTempView("bronze_orders")

    df = silver_orders(spark)
    assert df.count() == 2, f"Expected 2 rows (1 filtered), got {df.count()}"
    assert "total" in df.columns, "Missing 'total' column"
    assert "order_hour" in df.columns, "Missing 'order_hour' column"

    row = df.filter(f.col("order_id") == "1").first()
    assert abs(row["total"] - 19.98) < 0.01, f"Expected total ~19.98, got {row['total']}"
    assert row["order_hour"] == 14, f"Expected order_hour 14, got {row['order_hour']}"

    print("All tests passed!")
    df.show(truncate=False)
    spark.stop()
