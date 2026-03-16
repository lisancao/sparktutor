"""
Enrich Trips — Solution

Adds time_bucket, is_surge, and distance_category to trips.
"""

from pyspark.sql import SparkSession, functions as f


def enrich_trips(trips_df):
    """
    Add time_bucket (morning_rush/evening_rush/off_peak), is_surge,
    and distance_category (short/medium/long) to trips.
    """
    with_ts = trips_df.withColumn("pickup_ts", f.to_timestamp("pickup_time"))
    with_time_bucket = with_ts.withColumn(
        "time_bucket",
        f.when(f.hour("pickup_ts").between(6, 9), "morning_rush")
        .when(f.hour("pickup_ts").between(17, 20), "evening_rush")
        .otherwise("off_peak"),
    )
    with_surge = with_time_bucket.withColumn(
        "is_surge", (f.col("fare") > 15) & (f.col("distance_miles") < 5)
    )
    enriched = with_surge.withColumn(
        "distance_category",
        f.when(f.col("distance_miles") < 3, "short")
        .when(f.col("distance_miles") < 10, "medium")
        .otherwise("long"),
    )
    return enriched


# ---- Test harness ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("Test").master("local[*]").getOrCreate()

    trips_data = [
        ("SF", "r1", 18.00, 2.5, "2024-01-15 08:30:00"),
        ("NYC", "r2", 12.00, 8.0, "2024-01-15 18:00:00"),
        ("SF", "r3", 8.75, 2.0, "2024-01-15 14:00:00"),
    ]
    cols = ["city", "rider_id", "fare", "distance_miles", "pickup_time"]
    trips_df = spark.createDataFrame(trips_data, cols)

    result = enrich_trips(trips_df)
    assert result is not None, "Function returned None"
    assert "time_bucket" in result.columns
    assert "is_surge" in result.columns
    assert "distance_category" in result.columns

    rows = result.collect()
    sf_morning = next(r for r in rows if r.city == "SF" and "08" in str(r.pickup_time))
    assert sf_morning.time_bucket == "morning_rush", f"Expected morning_rush, got {sf_morning.time_bucket}"
    assert sf_morning.is_surge == True, f"Expected is_surge True (fare 18, dist 2.5), got {sf_morning.is_surge}"
    assert sf_morning.distance_category == "short", f"Expected short, got {sf_morning.distance_category}"

    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
