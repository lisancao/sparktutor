"""
Rank Drivers and 7-Day Moving Average — Solution

Ranks drivers by earnings per city; computes 7-day moving average.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.window import Window


def rank_drivers_by_earnings(trips_df):
    """
    Return DataFrame with city, driver_id, total_fare, rank.
    Rank is row_number by total_fare desc within city.
    """
    driver_fares = trips_df.groupBy("city", "driver_id").agg(
        f.sum("fare").alias("total_fare")
    )
    w = Window.partitionBy("city").orderBy(f.col("total_fare").desc())
    ranked = driver_fares.withColumn("rank", f.row_number().over(w))
    return ranked


def trips_7d_moving_avg(daily_trips_df):
    """
    Add trips_7d_ma = 7-day moving average of trips.
    daily_trips has city, date, trips.
    """
    w = (
        Window.partitionBy("city")
        .orderBy("date")
        .rowsBetween(-6, 0)
    )
    result = daily_trips_df.withColumn(
        "trips_7d_ma", f.avg("trips").over(w)
    )
    return result


# ---- Test harness ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("Test").master("local[*]").getOrCreate()

    trips_data = [
        ("d1", "SF", 20.0),
        ("d2", "SF", 30.0),
        ("d3", "SF", 25.0),
        ("d4", "NYC", 40.0),
    ]
    trips_df = spark.createDataFrame(trips_data, ["driver_id", "city", "fare"])

    ranked = rank_drivers_by_earnings(trips_df)
    assert ranked is not None, "rank_drivers_by_earnings returned None"
    assert "rank" in ranked.columns
    sf_rank1 = ranked.filter((f.col("city") == "SF") & (f.col("rank") == 1)).collect()[0]
    assert sf_rank1.driver_id == "d2", f"SF rank 1 should be d2 (30), got {sf_rank1.driver_id}"

    daily_data = [(c, f"2024-01-{d:02d}", 10 + d) for c in ["SF", "NYC"] for d in range(1, 16)]
    daily_df = spark.createDataFrame(daily_data, ["city", "date", "trips"])
    ma_df = trips_7d_moving_avg(daily_df)
    assert "trips_7d_ma" in ma_df.columns
    sf_day7 = ma_df.filter((f.col("city") == "SF") & (f.col("date") == "2024-01-07")).collect()[0]
    expected_ma = (10+11+12+13+14+15+16) / 7
    assert abs(sf_day7.trips_7d_ma - expected_ma) < 0.01, f"Expected ~13, got {sf_day7.trips_7d_ma}"
    print("All tests passed!")
    ranked.show()
    ma_df.filter(f.col("city") == "SF").show(10, truncate=False)
    spark.stop()
