"""
Silver — Type Casting (Starter)

Implement silver_clicks(spark, bronze_df) that casts bronze click events
to proper types and routes failed casts to quarantine.

Returns (valid_df, quarantine_df).
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType


def silver_clicks(spark, bronze_df):
    """
    Cast bronze clicks to silver. Route timestamp cast failures to quarantine.
    Returns (valid_df, quarantine_df).
    """
    # TODO: Add casted timestamp column
    # TODO: Split into valid (timestamp not null) and quarantine (timestamp null)
    # TODO: Add _quarantine_reason and _quarantine_at to quarantine
    return (None, None)


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("SilverCast").master("local[*]").getOrCreate()

    bronze_data = [
        ("e1", "u1", "p1", "click", "2024-01-15 10:00:00"),
        ("e2", "u2", "p2", "view", "2024-01-15 10:01:00"),
        ("e3", "u3", "p3", "click", "invalid"),
    ]
    schema = StructType([
        StructField("event_id", StringType()),
        StructField("user_id", StringType()),
        StructField("product_id", StringType()),
        StructField("event_type", StringType()),
        StructField("timestamp", StringType()),
    ])
    bronze_df = spark.createDataFrame(bronze_data, schema)

    valid, quarantine = silver_clicks(spark, bronze_df)
    assert valid is not None and quarantine is not None
    assert valid.count() == 2, f"valid: expected 2, got {valid.count()}"
    assert quarantine.count() == 1, f"quarantine: expected 1, got {quarantine.count()}"
    assert "_quarantine_reason" in quarantine.columns
    assert "_quarantine_at" in quarantine.columns
    print("All tests passed!")
    spark.stop()
