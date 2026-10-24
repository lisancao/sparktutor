"""
VARIANT - Solution

Parse a heterogeneous event feed into VARIANT and query it with paths.
"""

from pyspark.sql import SparkSession, functions as sf


RAW_EVENTS = [
    ('{"type": "click", "user": {"id": 1, "plan": "free"}, "page": "/home"}',),
    ('{"type": "purchase", "user": {"id": 2, "plan": "pro"}, "amount": 49.5, "items": ["a", "b"]}',),
    ('{"type": "purchase", "user": {"id": 1, "plan": "free"}, "amount": "12.00", "items": ["c"]}',),
    ('{"type": "purchase", "user": {"id": 3}, "amount": "n/a", "items": []}',),
    ('{"type": "click", "user": {"id": 2, "plan": "pro"}, "page": "/pricing", "ab": {"variant": "B"}}',),
    ('{not json',),
]


def analyze_events(spark):
    """Return parsed events, data-quality counts and a purchase summary."""

    raw = spark.createDataFrame(RAW_EVENTS, "raw string")
    raw.createOrReplaceTempView("raw_events")

    # 1. try_parse_json returns NULL for malformed JSON instead of failing.
    parsed = spark.sql("SELECT try_parse_json(raw) AS v FROM raw_events")
    parsed.createOrReplaceTempView("events")
    malformed = parsed.filter(sf.col("v").isNull()).count()

    # 2. Path extraction with the `:` operator (4.1) and `::` casts (4.0).
    #    try_variant_get returns NULL when the value cannot be cast.
    flat = spark.sql("""
        SELECT
          v:type::string                          AS event_type,
          v:user.id::int                          AS user_id,
          v:user.plan::string                     AS plan,
          try_variant_get(v, '$.amount', 'double') AS amount,
          v:items                                 AS items
        FROM events
        WHERE v IS NOT NULL
    """)

    # 3. One merged schema across all rows, to see what the feed contains.
    merged_schema = spark.sql(
        "SELECT schema_of_variant_agg(v) AS s FROM events WHERE v IS NOT NULL"
    ).first()["s"]

    # 4. Revenue per user from purchases whose amount could be read.
    revenue = (flat
        .filter((sf.col("event_type") == "purchase") & sf.col("amount").isNotNull())
        .groupBy("user_id")
        .agg(sf.sum("amount").alias("revenue"))
        .orderBy("user_id"))

    unreadable_amounts = flat.filter(
        (sf.col("event_type") == "purchase") & sf.col("amount").isNull()
    ).count()

    return {
        "flat": flat,
        "malformed": malformed,
        "merged_schema": merged_schema,
        "revenue": revenue,
        "unreadable_amounts": unreadable_amounts,
    }


# ---- Test harness ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("VariantTest")
        .master("local[*]")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate())

    result = analyze_events(spark)
    assert result is not None, "Function returned None"
    assert result["malformed"] == 1, f"Expected 1 malformed row, got {result['malformed']}"
    assert result["flat"].count() == 5, "Expected 5 parsed events"
    assert dict(result["flat"].dtypes)["items"] == "variant", "items should stay a VARIANT"
    assert result["unreadable_amounts"] == 1, "The 'n/a' amount should not be readable"
    rev = {r["user_id"]: r["revenue"] for r in result["revenue"].collect()}
    assert rev == {1: 12.0, 2: 49.5}, f"Unexpected revenue: {rev}"
    schema = result["merged_schema"]
    assert schema.startswith("OBJECT<") and "ab:" in schema and "amount:" in schema, schema
    print("Merged schema:", schema)
    result["flat"].show(truncate=False)
    result["revenue"].show()
    print("All tests passed!")
    spark.stop()
