"""
SQL Reporting Layer — Solution

Registers DataFrames as views and builds driver profiles via SQL.
"""

from pyspark.sql import SparkSession, functions as f


def build_sql_reporting_layer(spark, trips_df, drivers_df, ratings_df):
    """
    Register trips, drivers, ratings as views. Run SQL to compute
    driver profiles (total_trips, total_fare, avg_rating). Return result.
    """
    trips_df.createOrReplaceTempView("trips")
    drivers_df.createOrReplaceTempView("drivers")
    ratings_df.createOrReplaceTempView("ratings")

    result = spark.sql("""
        SELECT t.driver_id, d.name,
               COUNT(*) AS total_trips,
               SUM(t.fare) AS total_fare,
               AVG(r.rating) AS avg_rating
        FROM trips t
        JOIN drivers d ON t.driver_id = d.driver_id
        LEFT JOIN ratings r ON t.trip_id = r.trip_id
        GROUP BY t.driver_id, d.name
    """)
    return result


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
    drivers_df = spark.createDataFrame(drivers_data, ["driver_id", "name", "city", "vehicle_count"])

    ratings_data = [("r1", "t1", "r1", 5, "great"), ("r2", "t2", "r2", 4, "good")]
    ratings_df = spark.createDataFrame(ratings_data, ["rating_id", "trip_id", "rider_id", "rating", "comment"])

    result = build_sql_reporting_layer(spark, trips_df, drivers_df, ratings_df)
    assert result is not None, "Function returned None"
    assert result.count() == 2, f"Expected 2 drivers, got {result.count()}"
    d1 = result.filter(f.col("driver_id") == "d1").collect()[0]
    assert d1.total_trips == 2, f"d1 has 2 trips, got {d1.total_trips}"
    assert d1.total_fare == 34.5, f"d1 total fare 34.5, got {d1.total_fare}"
    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
