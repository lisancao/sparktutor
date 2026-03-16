"""
Filter and Enrich Trips — Solution

Filters trips by date range and adds trip_duration and fare_per_mile.
"""

from pyspark.sql import SparkSession, functions as f


def filter_and_enrich_trips(trips_df):
    """
    Filter trips by date range (2024-01-15 to 2024-01-16) and add
    trip_duration (placeholder 0) and fare_per_mile.
    """
    filtered = trips_df.filter(
        (f.col("pickup_time") >= "2024-01-15")
        & (f.col("pickup_time") < "2024-01-17")
    )
    with_duration = filtered.withColumn("trip_duration", f.lit(0))
    enriched = with_duration.withColumn(
        "fare_per_mile", f.col("fare") / f.col("distance_miles")
    )
    return enriched


# ---- Test harness ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("Test").master("local[*]").getOrCreate()

    trips_data = [
        ("SF", "r1", 12.50, 5.2, "2024-01-15 08:30:00"),
        ("NYC", "r2", 22.00, 8.1, "2024-01-14 09:15:00"),
        ("SF", "r3", 8.75, 3.0, "2024-01-15 10:00:00"),
        ("LA", "r1", 15.00, 6.5, "2024-01-16 11:00:00"),
    ]
    cols = ["city", "rider_id", "fare", "distance_miles", "pickup_time"]
    trips_df = spark.createDataFrame(trips_data, cols)

    result = filter_and_enrich_trips(trips_df)
    assert result is not None, "Function returned None"
    rows = result.collect()
    assert len(rows) == 3, f"Expected 3 rows (exclude 2024-01-14), got {len(rows)}"
    assert "fare_per_mile" in result.columns, "Missing fare_per_mile column"
    assert "trip_duration" in result.columns, "Missing trip_duration column"
    for r in rows:
        assert r.fare_per_mile == r.fare / r.distance_miles
        assert r.trip_duration == 0
    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
