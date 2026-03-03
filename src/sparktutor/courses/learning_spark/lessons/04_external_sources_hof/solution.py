"""
External Data Sources & Higher-Order Functions - Solution

Complete order analysis with higher-order functions and window ranking.
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

    with_upper = orders_df.withColumn(
        "items_upper", f.transform("items", lambda x: f.upper(x))
    )

    with_p_items = with_upper.withColumn(
        "p_items", f.filter("items", lambda x: x.startswith("p"))
    )

    w = Window.partitionBy("region").orderBy(f.col("total").desc())
    result = with_p_items.withColumn("region_rank", f.rank().over(w))

    return result


# ---- Test harness ----
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

    first_upper = df.filter(f.col("order_id") == 1).select("items_upper").collect()[0][0]
    assert first_upper == ["PEN", "PAPER", "PENCIL"], f"items_upper wrong: {first_upper}"

    print("All tests passed!")
    df.show(truncate=False)
    spark.stop()
