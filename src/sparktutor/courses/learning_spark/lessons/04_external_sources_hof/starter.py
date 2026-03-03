"""
External Data Sources & Higher-Order Functions - Starter Code

Implement the `analyze_orders` function that:
1. Creates a DataFrame of orders with an array column "items"
2. Uses transform() to uppercase all items in each order
3. Uses filter() to keep only items starting with "p"
4. Adds a window-based rank by total (descending) within each region
5. Returns the result DataFrame

This exercise covers higher-order functions and window functions.
"""

from pyspark.sql import SparkSession, functions as f, Window
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, ArrayType, DoubleType
)


ORDER_DATA = [
    (1, "West", 150.0, ["pen", "paper", "pencil"]),
    (2, "West", 280.0, ["printer", "paper", "ink"]),
    (3, "East", 95.0,  ["pencil", "eraser"]),
    (4, "East", 320.0, ["projector", "screen", "cable"]),
    (5, "West", 210.0, ["phone", "case", "charger"]),
    (6, "East", 175.0, ["paper", "pen", "folder"]),
]

SCHEMA = StructType([
    StructField("order_id", IntegerType(), False),
    StructField("region", StringType(), False),
    StructField("total", DoubleType(), False),
    StructField("items", ArrayType(StringType()), False),
])


def analyze_orders(spark):
    """Analyze orders using higher-order functions and windows."""

    orders_df = spark.createDataFrame(ORDER_DATA, SCHEMA)

    # TODO: Use transform() to uppercase all items in the "items" array
    #       Add as a new column called "items_upper"
    with_upper = None  # Replace

    # TODO: Use filter() on "items" to keep only items starting with "p"
    #       Add as a new column called "p_items"
    with_p_items = None  # Replace

    # TODO: Add a rank column "region_rank" that ranks orders by total
    #       (descending) within each region using a window function
    w = None  # Define the window spec
    result = None  # Add the rank column

    return result


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("HOFTest")
        .master("local[*]")
        .getOrCreate())

    df = analyze_orders(spark)
    assert df is not None, "Function returned None"
    assert "items_upper" in df.columns, "Missing items_upper column"
    assert "p_items" in df.columns, "Missing p_items column"
    assert "region_rank" in df.columns, "Missing region_rank column"
    assert df.count() == 6, f"Expected 6 rows, got {df.count()}"

    # Check uppercase transform worked
    first_upper = df.filter(f.col("order_id") == 1).select("items_upper").collect()[0][0]
    assert first_upper == ["PEN", "PAPER", "PENCIL"], f"items_upper wrong: {first_upper}"

    print("All tests passed!")
    df.show(truncate=False)
    spark.stop()
