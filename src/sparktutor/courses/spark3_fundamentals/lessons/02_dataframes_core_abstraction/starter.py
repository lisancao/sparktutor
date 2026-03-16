"""
Filter and Enrich Trips — Starter Code

Filter trips by date range and add computed columns for trip_duration
and fare_per_mile.
"""

from pyspark.sql import SparkSession, functions as f


def filter_and_enrich_trips(trips_df):
    """
    Filter trips by date range (2024-01-15 to 2024-01-16) and add
    trip_duration (placeholder 0) and fare_per_mile.
    """

    # TODO: Filter for pickup_time between 2024-01-15 and 2024-01-16
    # filtered = ...

    # TODO: Add trip_duration column (placeholder 0 for now)
    # with_duration = ...

    # TODO: Add fare_per_mile as fare / distance_miles
    # enriched = ...

    pass


# ---- Test harness (do not modify below this line) ----
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
