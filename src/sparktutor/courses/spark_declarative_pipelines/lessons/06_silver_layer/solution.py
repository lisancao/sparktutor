"""
Silver Layer - Solution

Clean, type-cast, and enrich bronze data into silver.
"""

from pyspark.sql import SparkSession, functions as f


def silver_orders(spark):
    """Transform bronze_orders into a clean silver DataFrame."""

    bronze = spark.table("bronze_orders")

    # Cast string columns to proper types
    typed = (bronze
        .withColumn("price", f.col("price").cast("double"))
        .withColumn("quantity", f.col("quantity").cast("int"))
    )

    # Compute total
    with_total = typed.withColumn("total", f.col("price") * f.col("quantity"))

    # Filter out rows where price could not be parsed
    clean = with_total.filter(f.col("price").isNotNull())

    # Extract hour from the order timestamp string
    enriched = clean.withColumn("order_hour", f.hour(f.to_timestamp(f.col("order_ts"))))

    return enriched


# ---- Test harness ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("SilverTest").master("local[*]").getOrCreate()

    data = [
        ("1", "widget", "9.99", "2", "2026-01-15 14:30:00"),
        ("2", "gadget", "24.99", "1", "2026-01-15 09:15:00"),
        ("3", "doohickey", "N/A", "3", "2026-01-15 22:00:00"),
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
