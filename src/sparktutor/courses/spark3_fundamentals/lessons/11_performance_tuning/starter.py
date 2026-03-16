"""
Optimize Pipeline — Starter Code

Apply tuning: config, broadcast join, cache, unpersist.
"""

from pyspark.sql import SparkSession, functions as f


def optimize_pipeline(spark, trips_df, drivers_df, ratings_df):
    """
    Join trips with drivers (broadcast) and ratings, cache, compute
    city_stats and driver_stats, unpersist, return (city_stats, driver_stats).
    """

    # TODO: Join trips with drivers (broadcast), then left join ratings
    # joined = ...

    # TODO: Cache the joined DataFrame
    # joined.cache()

    # TODO: city_stats = groupBy city, count
    # city_stats = ...

    # TODO: driver_stats = groupBy driver_id, sum fare
    # driver_stats = ...

    # TODO: Unpersist
    # joined.unpersist()

    pass


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = (
        SparkSession.builder
        .appName("Test")
        .master("local[*]")
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.sql.autoBroadcastJoinThreshold", "20971520")
        .getOrCreate()
    )

    trips_data = [
        ("t1", "SF", "d1", "r1", 12.5, 5.2, "2024-01-15 08:30:00"),
        ("t2", "SF", "d1", "r2", 22.0, 8.1, "2024-01-15 09:15:00"),
        ("t3", "NYC", "d2", "r3", 15.0, 6.0, "2024-01-15 10:00:00"),
    ]
    trips_cols = ["trip_id", "city", "driver_id", "rider_id", "fare", "distance_miles", "pickup_time"]
    trips_df = spark.createDataFrame(trips_data, trips_cols)

    drivers_data = [("d1", "Alice", "SF", 2), ("d2", "Bob", "NYC", 1)]
    drivers_df = spark.createDataFrame(drivers_data, ["driver_id", "name", "city", "vehicle_count"])

    ratings_data = [("r1", "t1", "r1", 5, "great")]
    ratings_df = spark.createDataFrame(ratings_data, ["rating_id", "trip_id", "rider_id", "rating", "comment"])

    city_stats, driver_stats = optimize_pipeline(spark, trips_df, drivers_df, ratings_df)
    assert city_stats.count() == 2, f"Expected 2 cities, got {city_stats.count()}"
    assert driver_stats.count() == 2, f"Expected 2 drivers, got {driver_stats.count()}"
    sf_trips = city_stats.filter(f.col("city") == "SF").collect()[0].trip_count
    assert sf_trips == 2, f"SF has 2 trips, got {sf_trips}"
    print("All tests passed!")
    city_stats.show()
    driver_stats.show()
    spark.stop()
