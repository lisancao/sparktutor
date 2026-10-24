"""
Complex Types & Higher-Order Functions - Starter Code

Implement the `analyze_orders` function that:
1. Creates a DataFrame of orders with an array column "items" and a JSON
   string column "attrs"
2. Uses transform() to uppercase all items in each order ("items_upper")
3. Uses filter() to keep only items starting with "p" ("p_items")
4. Parses "attrs" with parse_json() and extracts $.priority as a string
   column "priority" with variant_get()
5. Adds a window-based rank by total (descending) within each region
   ("region_rank")
6. Returns the result DataFrame

This exercise covers higher-order functions, the VARIANT type, and window
functions.
"""

from pyspark.sql import SparkSession, functions as f, Window
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, ArrayType, DoubleType
)


ORDER_DATA = [
    (1, "West", 150.0, ["pen", "paper", "pencil"], '{"priority": "high", "gift": true}'),
    (2, "West", 280.0, ["printer", "paper", "ink"], '{"priority": "low"}'),
    (3, "East", 95.0,  ["pencil", "eraser"], '{"priority": "low", "coupon": "SAVE5"}'),
    (4, "East", 320.0, ["projector", "screen", "cable"], '{"priority": "high"}'),
    (5, "West", 210.0, ["phone", "case", "charger"], '{"priority": "medium", "gift": false}'),
    (6, "East", 175.0, ["paper", "pen", "folder"], '{"priority": "medium"}'),
]

SCHEMA = StructType([
    StructField("order_id", IntegerType(), False),
    StructField("region", StringType(), False),
    StructField("total", DoubleType(), False),
    StructField("items", ArrayType(StringType()), False),
    StructField("attrs", StringType(), False),  # JSON with a varying shape
])


def analyze_orders(spark):
    """Analyze orders using higher-order functions, VARIANT, and windows."""

    orders_df = spark.createDataFrame(ORDER_DATA, SCHEMA)

    # TODO: Use transform() to uppercase all items in the "items" array
    #       Add as a new column called "items_upper"
    with_upper = None  # Replace

    # TODO: Use filter() on "items" to keep only items starting with "p"
    #       Add as a new column called "p_items"
    with_p_items = None  # Replace

    # TODO: Parse "attrs" into a VARIANT with f.parse_json and pull out
    #       "$.priority" as a string column called "priority"
    with_priority = None  # Replace

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
    for col_name in ["items_upper", "p_items", "priority", "region_rank"]:
        assert col_name in df.columns, f"Missing {col_name} column"
    assert df.count() == 6, f"Expected 6 rows, got {df.count()}"

    # Check uppercase transform worked
    first = df.filter(f.col("order_id") == 1).first()
    assert first["items_upper"] == ["PEN", "PAPER", "PENCIL"], f"items_upper wrong: {first['items_upper']}"
    assert first["p_items"] == ["pen", "paper", "pencil"], f"p_items wrong: {first['p_items']}"

    # Check the VARIANT extraction
    assert first["priority"] == "high", f"priority wrong: {first['priority']}"
    assert dict(df.dtypes)["priority"] == "string", "priority should be a string column"

    # Check the window rank: order 4 is the largest East order
    top_east = df.filter((f.col("region") == "East") & (f.col("region_rank") == 1)).first()
    assert top_east["order_id"] == 4, f"Expected order 4 to rank first in East, got {top_east}"

    print("All tests passed!")
    df.drop("attrs").show(truncate=False)
    spark.stop()
