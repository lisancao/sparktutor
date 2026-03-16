"""
Enrich Trips — Starter Code

Add time_bucket, is_surge, and distance_category columns to trips.
"""

from pyspark.sql import SparkSession, functions as f


def enrich_trips(trips_df):
    """
    Add time_bucket (morning_rush/evening_rush/off_peak), is_surge,
    and distance_category (short/medium/long) to trips.
    """

    # TODO: Convert pickup_time to timestamp and extract hour
    # with_ts = ...

    # TODO: Add time_bucket based on hour
    # with_time_bucket = ...

    # TODO: Add is_surge (fare > 15 and distance_miles < 5)
    # with_surge = ...

    # TODO: Add distance_category (short < 3, medium 3-10, long > 10)
    # enriched = ...

    pass


# ---- Test harness (do not modify below this line) ----
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
    assert "time_bucket" in result.columns, "Missing time_bucket"
    assert "is_surge" in result.columns, "Missing is_surge"
    assert "distance_category" in result.columns, "Missing distance_category"

    rows = result.collect()
    sf_morning = next(r for r in rows if r.city == "SF" and "08" in str(r.pickup_time))
    assert sf_morning.time_bucket == "morning_rush", f"Expected morning_rush, got {sf_morning.time_bucket}"
    assert sf_morning.is_surge == True, f"Expected is_surge True (fare 18, dist 2.5), got {sf_morning.is_surge}"
    assert sf_morning.distance_category == "short", f"Expected short, got {sf_morning.distance_category}"

    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
