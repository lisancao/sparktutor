"""
Trips per City — Solution

Creates SparkSession, builds trips DataFrame, and computes ride counts per city.
"""

from pyspark.sql import SparkSession, functions as f

TRIPS_DATA = [
    ("SF", "r1", 12.50, 5.2, "2024-01-15 08:30:00"),
    ("NYC", "r2", 22.00, 8.1, "2024-01-15 09:15:00"),
    ("SF", "r3", 8.75, 3.0, "2024-01-15 10:00:00"),
    ("LA", "r1", 15.00, 6.5, "2024-01-15 11:00:00"),
    ("SF", "r2", 6.25, 2.1, "2024-01-15 12:00:00"),
]
COLUMNS = ["city", "rider_id", "fare", "distance_miles", "pickup_time"]


def trips_per_city(spark):
    """
    Create SparkSession, build trips DataFrame, and return ride counts per city.
    """
    trips_df = spark.createDataFrame(TRIPS_DATA, COLUMNS)
    result = (
        trips_df.groupBy("city")
        .agg(f.count("*").alias("ride_count"))
        .orderBy(f.col("ride_count").desc())
    )
    return result


# ---- Test harness ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("Test").master("local[*]").getOrCreate()

    result = trips_per_city(spark)
    assert result is not None, "Function returned None"
    rows = result.collect()
    assert len(rows) >= 1, f"Expected at least 1 city, got {len(rows)}"
    cities = [r.city for r in rows]
    assert "SF" in cities, f"Expected SF in results, got {cities}"
    sf_row = next(r for r in rows if r.city == "SF")
    assert sf_row.ride_count == 3, f"Expected SF to have 3 rides, got {sf_row.ride_count}"
    assert rows[0].ride_count >= rows[-1].ride_count, "Expected descending order by ride_count"
    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
