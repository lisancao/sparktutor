"""
Collation Support — Fix Multi-Language Product Catalog Matching

Match products by name case-insensitively using collation or lower().
"""

from pyspark.sql import SparkSession, DataFrame, functions as f

PRODUCTS_DATA = [
    ("p1", "Widget"),
    ("p2", "WIDGET"),
    ("p3", "Gadget"),
    ("p4", "GADGET"),
    ("p5", "Café"),
]
PRODUCTS_COLUMNS = ["product_id", "name"]


def match_products_case_insensitive(spark, name: str) -> DataFrame:
    """
    Return products whose name matches the given name, case-insensitively.
    Use collate("utf8mb4_0900_ai_ci") if available, else lower(name) == lower(input).
    """
    df = spark.createDataFrame(PRODUCTS_DATA, PRODUCTS_COLUMNS)

    # TODO: Filter by name case-insensitively
    # Try: f.col("name").collate("utf8mb4_0900_ai_ci") == name
    # Fallback: f.lower(f.col("name")) == f.lower(f.lit(name))

    pass


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("Collation").master("local[*]").getOrCreate()
    result = match_products_case_insensitive(spark, "Widget")
    assert result is not None, "Function returned None"
    rows = result.collect()
    assert len(rows) == 2, f"Expected 2 rows (Widget, WIDGET), got {len(rows)}"
    names = [r.name for r in rows]
    assert "Widget" in names and "WIDGET" in names
    result2 = match_products_case_insensitive(spark, "gadget")
    assert result2.count() == 2
    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
