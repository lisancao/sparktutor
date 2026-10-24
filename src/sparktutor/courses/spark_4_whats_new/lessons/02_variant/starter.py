"""
VARIANT - Starter Code

Implement `analyze_events(spark)`. It must:
1. Parse the `raw` column with try_parse_json into a temp view `events`
   (column `v`) and count malformed rows (v IS NULL)
2. Build `flat` from parsed rows with columns:
   event_type (string), user_id (int), plan (string),
   amount (double, via try_variant_get), items (left as VARIANT)
3. Compute the merged schema with schema_of_variant_agg
4. Sum amount per user_id for purchases with a readable amount, and
   count purchases whose amount could not be read
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

    # TODO: parsed = spark.sql("SELECT try_parse_json(raw) AS v FROM raw_events")
    #       register it as the temp view "events" and count rows where v is NULL
    malformed = None  # Replace

    # TODO: Build `flat` with spark.sql over `events` (skip NULL v):
    #       v:type::string AS event_type, v:user.id::int AS user_id, ...
    #       amount must use try_variant_get(v, '$.amount', 'double')
    flat = None  # Replace

    # TODO: merged_schema = schema_of_variant_agg(v) over parsed rows (a string)
    merged_schema = None  # Replace

    # TODO: revenue per user_id for purchases with a non-NULL amount,
    #       column name "revenue", ordered by user_id
    revenue = None  # Replace

    # TODO: count purchases where amount is NULL
    unreadable_amounts = None  # Replace

    return {
        "flat": flat,
        "malformed": malformed,
        "merged_schema": merged_schema,
        "revenue": revenue,
        "unreadable_amounts": unreadable_amounts,
    }


# ---- Test harness (do not modify below this line) ----
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
