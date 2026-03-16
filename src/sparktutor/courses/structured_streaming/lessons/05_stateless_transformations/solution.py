"""
Stateless Transformations — Solution

Enrich transactions with risk_score, merchant_category, and time_of_day.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, TimestampType

SCHEMA = StructType([
    StructField("tx_id", StringType(), False),
    StructField("user_id", StringType(), False),
    StructField("amount", DoubleType(), False),
    StructField("event_time", TimestampType(), False),
])

TRANSACTIONS = [
    ("tx1", "u1", 50.0, "2024-01-15 03:00:00"),
    ("tx2", "u2", 250.0, "2024-01-15 09:00:00"),
    ("tx3", "u1", 600.0, "2024-01-15 14:00:00"),
    ("tx4", "u3", 150.0, "2024-01-15 20:00:00"),
]


def enrich_transactions(spark, transactions_df):
    """Add risk_score, merchant_category, time_of_day."""
    return (transactions_df
        .withColumn("risk_score",
            f.when(f.col("amount") >= 500, 0.9)
            .when(f.col("amount") >= 100, 0.6)
            .otherwise(0.3))
        .withColumn("merchant_category",
            f.when(f.col("amount") < 200, "retail").otherwise("premium"))
        .withColumn("time_of_day",
            f.when(f.hour("event_time") < 6, "night")
            .when(f.hour("event_time") < 12, "morning")
            .when(f.hour("event_time") < 18, "afternoon")
            .otherwise("evening")))


if __name__ == "__main__":
    spark = SparkSession.builder.appName("PayGuardStateless").master("local[*]").getOrCreate()

    tx_df = spark.createDataFrame(TRANSACTIONS, SCHEMA)
    result = enrich_transactions(spark, tx_df)

    assert result is not None
    assert "risk_score" in result.columns
    assert "merchant_category" in result.columns
    assert "time_of_day" in result.columns

    rows = result.collect()
    r1 = next(r for r in rows if r.tx_id == "tx1")
    assert r1.risk_score == 0.3 and r1.merchant_category == "retail" and r1.time_of_day == "night"
    r3 = next(r for r in rows if r.tx_id == "tx3")
    assert r3.risk_score == 0.9 and r3.merchant_category == "premium"

    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
