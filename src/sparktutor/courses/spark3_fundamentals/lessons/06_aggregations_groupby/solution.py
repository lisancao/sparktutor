"""
City Dashboard — Solution

Builds city-level metrics: trips per day, avg fare, peak hour.
"""

from pyspark.sql import SparkSession, functions as f


def city_dashboard(trips_df):
    """
    Return DataFrame with city, trips_per_day, avg_fare, peak_hour.
    trips_df has city, date, fare, pickup_time (and optionally distance_miles).
    """
    daily = trips_df.groupBy("city", "date").agg(f.count("*").alias("daily_trips"))
    trips_per_day_df = daily.groupBy("city").agg(
        f.avg("daily_trips").alias("trips_per_day")
    )
    avg_fare_df = trips_df.groupBy("city").agg(f.avg("fare").alias("avg_fare"))

    with_hour = trips_df.withColumn(
        "hour", f.hour(f.to_timestamp("pickup_time"))
    )
    city_hour_counts = with_hour.groupBy("city", "hour").agg(
        f.count("*").alias("cnt")
    )
    peak_df = city_hour_counts.groupBy("city").agg(
        f.max(f.struct(f.col("cnt"), f.col("hour"))).alias("peak_struct")
    ).withColumn("peak_hour", f.col("peak_struct.hour")).select("city", "peak_hour")

    dashboard = (
        trips_per_day_df.join(avg_fare_df, "city")
        .join(peak_df, "city")
    )
    return dashboard


# ---- Test harness ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("Test").master("local[*]").getOrCreate()

    trips_data = [
        ("SF", "2024-01-15", 12.5, "2024-01-15 08:30:00"),
        ("SF", "2024-01-15", 22.0, "2024-01-15 08:45:00"),
        ("SF", "2024-01-15", 8.75, "2024-01-15 14:00:00"),
        ("SF", "2024-01-16", 15.0, "2024-01-16 08:00:00"),
        ("NYC", "2024-01-15", 20.0, "2024-01-15 18:00:00"),
    ]
    cols = ["city", "date", "fare", "pickup_time"]
    trips_df = spark.createDataFrame(trips_data, cols)

    result = city_dashboard(trips_df)
    assert result is not None, "Function returned None"
    assert "trips_per_day" in result.columns
    assert "avg_fare" in result.columns
    assert "peak_hour" in result.columns

    sf = result.filter(f.col("city") == "SF").collect()[0]
    assert sf.trips_per_day == 2.0, f"SF has 2 days with 3 and 1 trips -> avg 2, got {sf.trips_per_day}"
    assert sf.peak_hour == 8, f"SF peak hour is 8 (3 trips at 8xx), got {sf.peak_hour}"
    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
