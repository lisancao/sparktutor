"""
Driver Performance Profiles — Solution

Joins trips with drivers and ratings, aggregates per driver.
"""

from pyspark.sql import SparkSession, functions as f


def driver_performance_profiles(trips_df, drivers_df, ratings_df):
    """
    Inner join trips-drivers, left join ratings, aggregate per driver:
    total_trips, total_fare, avg_rating.
    """
    joined = trips_df.join(f.broadcast(drivers_df), "driver_id", "inner")
    with_ratings = joined.join(ratings_df, "trip_id", "left")
    profiles = with_ratings.groupBy("driver_id").agg(
        f.count("*").alias("total_trips"),
        f.sum("fare").alias("total_fare"),
        f.avg("rating").alias("avg_rating"),
    )
    return profiles


# ---- Test harness ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("Test").master("local[*]").getOrCreate()

    trips_data = [
        ("t1", "SF", "d1", "r1", 12.5, 5.2, "2024-01-15 08:30:00"),
        ("t2", "SF", "d1", "r2", 22.0, 8.1, "2024-01-15 09:15:00"),
        ("t3", "NYC", "d2", "r3", 15.0, 6.0, "2024-01-15 10:00:00"),
    ]
    trips_cols = ["trip_id", "city", "driver_id", "rider_id", "fare", "distance_miles", "pickup_time"]
    trips_df = spark.createDataFrame(trips_data, trips_cols)

    drivers_data = [("d1", "Alice", "SF", 2), ("d2", "Bob", "NYC", 1)]
    drivers_cols = ["driver_id", "name", "city", "vehicle_count"]
    drivers_df = spark.createDataFrame(drivers_data, drivers_cols)

    ratings_data = [("r1", "t1", "r1", 5, "great"), ("r2", "t2", "r2", 4, "good")]
    ratings_cols = ["rating_id", "trip_id", "rider_id", "rating", "comment"]
    ratings_df = spark.createDataFrame(ratings_data, ratings_cols)

    result = driver_performance_profiles(trips_df, drivers_df, ratings_df)
    assert result is not None, "Function returned None"
    assert result.count() == 2, f"Expected 2 drivers, got {result.count()}"
    d1 = result.filter(f.col("driver_id") == "d1").collect()[0]
    assert d1.total_trips == 2, f"d1 has 2 trips, got {d1.total_trips}"
    assert d1.total_fare == 34.5, f"d1 total fare 34.5, got {d1.total_fare}"
    assert d1.avg_rating == 4.5, f"d1 avg rating (5+4)/2=4.5, got {d1.avg_rating}"
    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
