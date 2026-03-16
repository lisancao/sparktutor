"""
Variant Type — Migrate Product Catalog from get_json_object to VARIANT

Extract product name, category, price from JSON using parse_json and variant_get.
Fall back to get_json_object on Spark 3 if VARIANT APIs are unavailable.
"""

from pyspark.sql import SparkSession, DataFrame, functions as f

CATALOG_DATA = [
    ('p1', '{"name":"Widget","category":"Electronics","price":29.99}'),
    ('p2', '{"name":"Gadget","category":"Electronics","price":49.99}'),
    ('p3', '{"name":"T-Shirt","category":"Apparel","price":19.99}'),
]
CATALOG_COLUMNS = ["product_id", "json_str"]


def migrate_catalog_to_variant(spark) -> DataFrame:
    """
    Create catalog DataFrame, add variant column from json_str, extract
    name, category, price using variant_get. Fall back to get_json_object
    if parse_json/variant_get not available (Spark 3).
    Returns DataFrame with product_id, name, category, price.
    """
    df = spark.createDataFrame(CATALOG_DATA, CATALOG_COLUMNS)

    try:
        # TODO: parse_json to create variant column
        # TODO: variant_get for $.name, $.category, $.price
        pass
    except (AttributeError, TypeError):
        # Spark 3 fallback: get_json_object
        df = df.withColumn("name", f.get_json_object("json_str", "$.name"))
        df = df.withColumn("category", f.get_json_object("json_str", "$.category"))
        df = df.withColumn("price", f.get_json_object("json_str", "$.price").cast("double"))

    # TODO: Select product_id, name, category, price (drop json_str and variant if present)
    pass


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("VariantCatalog").master("local[*]").getOrCreate()
    result = migrate_catalog_to_variant(spark)
    assert result is not None, "Function returned None"
    rows = result.collect()
    assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}"
    assert "name" in result.columns and "category" in result.columns and "price" in result.columns
    p1 = next(r for r in rows if r.product_id == "p1")
    assert p1.name == "Widget", f"Expected Widget, got {p1.name}"
    assert abs(float(p1.price) - 29.99) < 0.01, f"Expected 29.99, got {p1.price}"
    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
