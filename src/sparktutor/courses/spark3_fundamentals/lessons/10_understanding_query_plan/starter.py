"""
Compare Query Plans — Starter Code

Build two equivalent pipelines (filter-then-join vs join-then-filter)
and compare their execution plans.
"""

from pyspark.sql import SparkSession, functions as f


def compare_plans(trips_df, drivers_df):
    """
    Return (df_a, df_b) where:
    - df_a: filter fare > 10, then join with drivers
    - df_b: join with drivers, then filter fare > 10
    """

    # TODO: df_a = filter trips by fare > 10, then join drivers
    # df_a = ...

    # TODO: df_b = join trips with drivers, then filter fare > 10
    # df_b = ...

    pass


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("Test").master("local[*]").getOrCreate()

    trips_data = [
        ("t1", "SF", "d1", "r1", 12.5, 5.2, "2024-01-15 08:30:00"),
        ("t2", "SF", "d1", "r2", 8.0, 3.0, "2024-01-15 09:15:00"),
        ("t3", "NYC", "d2", "r3", 15.0, 6.0, "2024-01-15 10:00:00"),
    ]
    trips_cols = ["trip_id", "city", "driver_id", "rider_id", "fare", "distance_miles", "pickup_time"]
    trips_df = spark.createDataFrame(trips_data, trips_cols)

    drivers_data = [("d1", "Alice", "SF", 2), ("d2", "Bob", "NYC", 1)]
    drivers_df = spark.createDataFrame(drivers_data, ["driver_id", "name", "city", "vehicle_count"])

    df_a, df_b = compare_plans(trips_df, drivers_df)
    assert df_a is not None and df_b is not None
    assert df_a.count() == df_b.count(), "Both should produce same row count"
    assert df_a.count() == 2, f"fare>10 gives t1 and t3, got {df_a.count()}"
    print("Both plans produce same result. Call df_a.explain(True) and df_b.explain(True) to compare.")
    df_a.explain(True)
    print("---")
    df_b.explain(True)
    spark.stop()
