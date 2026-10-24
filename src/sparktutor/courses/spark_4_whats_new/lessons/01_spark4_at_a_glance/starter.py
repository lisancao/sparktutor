"""
Spark 4 at a Glance - Starter Code

Implement `audit_payments(spark)`. It must:
1. Run the strict casts (amount -> double, qty -> int) inside a try block
   and capture (condition, sqlstate) from the PySparkException
2. Build a `clean` DataFrame using try_cast for both columns and a
   `unit_price` column computed with try_divide(amount, qty)
3. Count rows where amount or qty is NULL after cleaning
4. Trigger a Python-side error with spark.range(1).withColumn("x", 5)
   and capture its (condition, sqlstate)
5. Return the dict at the bottom of the function

The harness runs this on a Spark Connect session (spark.api.mode=connect).
"""

from pyspark.sql import SparkSession, functions as sf
from pyspark.errors import PySparkException


RAW_PAYMENTS = [
    ("p1", "120.50", "3"),
    ("p2", "abc", "2"),
    ("p3", "75.00", "0"),
    ("p4", "19.99", "1"),
    ("p5", "1e3", "x"),
    ("p6", None, "4"),
]


def audit_payments(spark):
    """Return the ANSI error, a cleaned DataFrame and some facts about the session."""

    raw = spark.createDataFrame(RAW_PAYMENTS, "payment_id string, amount string, qty string")

    # TODO: Run the strict casts and capture (e.getCondition(), e.getSqlState()).
    #       Hint: transformations are lazy; call .collect() so the cast executes.
    strict_error = None

    # TODO: Tolerant version. Select payment_id, amount (try_cast double),
    #       qty (try_cast int), then add unit_price = try_divide(amount, qty).
    clean = None  # Replace

    # TODO: Count rows where amount or qty is NULL in `clean`.
    bad_rows = None  # Replace

    # TODO: Capture (condition, sqlstate) from spark.range(1).withColumn("x", 5)
    python_error = None

    return {
        "strict_error": strict_error,
        "clean": clean,
        "bad_rows": bad_rows,
        "python_error": python_error,
        "ansi": spark.conf.get("spark.sql.ansi.enabled"),
        "arrow_udfs": spark.conf.get("spark.sql.execution.pythonUDF.arrow.enabled"),
        "is_connect": "connect" in type(spark).__module__,
    }


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    # spark.api.mode=connect starts a local Spark Connect server inside this
    # driver and hands back a Connect client session. Same code, new wire.
    spark = (SparkSession.builder
        .appName("Spark4AtAGlance")
        .config("spark.api.mode", "connect")
        .getOrCreate())

    result = audit_payments(spark)
    assert result is not None, "Function returned None"
    assert result["is_connect"], "Expected a Spark Connect session"
    assert result["ansi"] == "true", "ANSI mode should be on by default in Spark 4"
    assert result["arrow_udfs"] == "true", "Arrow-optimized Python UDFs are the 4.2 default"
    assert result["strict_error"] == ("CAST_INVALID_INPUT", "22018"), result["strict_error"]
    assert result["python_error"] is not None and result["python_error"][1] is not None, \
        "PySpark-side errors should expose a SQLSTATE"
    assert result["bad_rows"] == 3, f"Expected 3 bad rows, got {result['bad_rows']}"
    rows = {r["payment_id"]: r for r in result["clean"].collect()}
    assert rows["p3"]["unit_price"] is None, "Division by zero should be NULL via try_divide"
    assert abs(rows["p1"]["unit_price"] - 40.1666) < 0.01
    assert rows["p5"]["amount"] == 1000.0, "'1e3' is a valid double"
    print("Strict-mode error:", result["strict_error"])
    print("Python-side error:", result["python_error"])
    result["clean"].show()
    print("All tests passed!")
    spark.stop()
