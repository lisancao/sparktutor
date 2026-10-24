"""
Complex Types & Higher-Order Functions - Solution

Order analysis with higher-order functions, a VARIANT column parsed from
JSON, and window ranking.
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

    with_upper = orders_df.withColumn(
        "items_upper", f.transform("items", lambda x: f.upper(x))
    )

    with_p_items = with_upper.withColumn(
        "p_items", f.filter("items", lambda x: x.startswith("p"))
    )

    with_priority = with_p_items.withColumn(
        "priority", f.variant_get(f.parse_json("attrs"), "$.priority", "string")
    )

    w = Window.partitionBy("region").orderBy(f.col("total").desc())
    result = with_priority.withColumn("region_rank", f.rank().over(w))

    return result


# ---- Test harness ----
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
