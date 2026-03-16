"""
Trips, Drivers, and Ratings Schemas — Solution

Defines StructType schemas for trips, drivers, and ratings tables.
"""

from pyspark.sql.types import StructType, StructField, StringType, DoubleType, IntegerType


def get_trips_schema():
    """Return schema for trips table."""
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
    """Return schema for drivers table."""
    return StructType([
        StructField("driver_id", StringType(), False),
        StructField("name", StringType(), False),
        StructField("city", StringType(), True),
        StructField("vehicle_count", IntegerType(), True),
    ])


def get_ratings_schema():
    """Return schema for ratings table."""
    return StructType([
        StructField("rating_id", StringType(), False),
        StructField("trip_id", StringType(), False),
        StructField("rider_id", StringType(), False),
        StructField("rating", IntegerType(), False),
        StructField("comment", StringType(), True),
    ])


# ---- Test harness ----
if __name__ == "__main__":
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName("Test").master("local[*]").getOrCreate()

    trips_schema = get_trips_schema()
    assert trips_schema is not None, "get_trips_schema returned None"
    assert len(trips_schema.fields) == 7, f"Expected 7 fields in trips, got {len(trips_schema.fields)}"
    assert "fare" in [f.name for f in trips_schema.fields], "Missing fare in trips schema"

    drivers_schema = get_drivers_schema()
    assert drivers_schema is not None, "get_drivers_schema returned None"
    assert len(drivers_schema.fields) == 4, f"Expected 4 fields in drivers, got {len(drivers_schema.fields)}"

    ratings_schema = get_ratings_schema()
    assert ratings_schema is not None, "get_ratings_schema returned None"
    assert len(ratings_schema.fields) == 5, f"Expected 5 fields in ratings, got {len(ratings_schema.fields)}"

    trips_df = spark.createDataFrame([], schema=trips_schema)
    assert trips_df.schema == trips_schema
    print("All tests passed!")
    spark.stop()
