"""
Ride-Sharing Analytics Platform — Starter Code

Full end-to-end pipeline: read, enrich, join, aggregate, rank, write.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.window import Window
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, IntegerType


def get_trips_schema():
    return StructType([
        StructField("trip_id", StringType(), False),
        StructField("city", StringType(), False),
        StructField("driver_id", StringType(), True),
        StructField("rider_id", StringType(), False),
        StructField("fare", DoubleType(), False),
        StructField("distance_miles", DoubleType(), False),
        StructField("pickup_time", StringType(), False),
    ])


def get_drivers_schema():
    return StructType([
        StructField("driver_id", StringType(), False),
        StructField("name", StringType(), False),
        StructField("city", StringType(), True),
        StructField("vehicle_count", IntegerType(), True),
    ])


def get_ratings_schema():
    return StructType([
        StructField("rating_id", StringType(), False),
        StructField("trip_id", StringType(), False),
        StructField("rider_id", StringType(), False),
        StructField("rating", IntegerType(), False),
        StructField("comment", StringType(), True),
    ])


def run_analytics_platform(
    spark,
    trips_path,
    drivers_path,
    ratings_path,
    output_dir,
):
    """
    Full pipeline: read, enrich, join, aggregate, rank, write.
    Returns (city_dashboard, driver_profiles, top_drivers).
    """

    # TODO: Read trips, drivers, ratings with schemas
    # trips_df = ...
    # drivers_df = ...
    # ratings_df = ...

    # TODO: Enrich trips (time_bucket, fare_per_mile)
    # enriched_trips = ...

    # TODO: Join trips with drivers (broadcast) and ratings, cache
    # joined = ...

    # TODO: city_dashboard = trips per day, avg fare per city
    # city_dashboard = ...

    # TODO: driver_profiles = total_trips, total_fare, avg_rating per driver
    # driver_profiles = ...

    # TODO: top_drivers = rank by total_fare within city, filter rank <= 3
    # top_drivers = ...

    # TODO: Write city_dashboard and driver_profiles to Parquet
    # ...

    # TODO: Unpersist
    # joined.unpersist()

    pass


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    import tempfile
    import os

    spark = (
        SparkSession.builder
        .appName("Capstone")
        .master("local[*]")
        .config("spark.sql.shuffle.partitions", "8")
        .getOrCreate()
    )

    tmp = tempfile.mkdtemp()
    trips_path = os.path.join(tmp, "trips.csv")
    drivers_path = os.path.join(tmp, "drivers.csv")
    ratings_path = os.path.join(tmp, "ratings.csv")
    out_dir = os.path.join(tmp, "output")

    with open(trips_path, "w") as fh:
        fh.write("trip_id,city,driver_id,rider_id,fare,distance_miles,pickup_time\n")
        fh.write("t1,SF,d1,r1,12.5,5.2,2024-01-15 08:30:00\n")
        fh.write("t2,SF,d1,r2,22.0,8.1,2024-01-15 09:15:00\n")
        fh.write("t3,NYC,d2,r3,15.0,6.0,2024-01-15 10:00:00\n")
    with open(drivers_path, "w") as fh:
        fh.write("driver_id,name,city,vehicle_count\n")
        fh.write("d1,Alice,SF,2\n")
        fh.write("d2,Bob,NYC,1\n")
    with open(ratings_path, "w") as fh:
        fh.write("rating_id,trip_id,rider_id,rating,comment\n")
        fh.write("r1,t1,r1,5,great\n")
        fh.write("r2,t2,r2,4,good\n")

    city_dash, driver_profs, top_drivers = run_analytics_platform(
        spark, trips_path, drivers_path, ratings_path, out_dir
    )
    assert city_dash is not None and driver_profs is not None and top_drivers is not None
    assert city_dash.count() == 2, f"Expected 2 cities, got {city_dash.count()}"
    assert driver_profs.count() == 2, f"Expected 2 drivers, got {driver_profs.count()}"
    assert os.path.exists(os.path.join(out_dir, "city_dashboard")), "city_dashboard not written"
    assert os.path.exists(os.path.join(out_dir, "driver_profiles")), "driver_profiles not written"
    print("All tests passed!")
    city_dash.show()
    driver_profs.show()
    top_drivers.show()
    spark.stop()
