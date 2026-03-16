"""
Read CSV, Write Parquet — Solution

Reads trips CSV with schema and writes Parquet partitioned by date.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType


def get_trips_schema():
    """Trips schema (from Lesson 3)."""
    return StructType([
        StructField("trip_id", StringType(), False),
        StructField("city", StringType(), False),
        StructField("driver_id", StringType(), True),
        StructField("rider_id", StringType(), False),
        StructField("fare", DoubleType(), False),
        StructField("distance_miles", DoubleType(), False),
        StructField("pickup_time", StringType(), False),
    ])


def ingest_trips_to_parquet(spark, input_path, output_path):
    """
    Read trips CSV with schema, add date column, write Parquet partitioned by date.
    """
    trips_df = (
        spark.read.format("csv")
        .option("header", "true")
        .schema(get_trips_schema())
        .load(input_path)
    )
    with_date = trips_df.withColumn("date", f.substring("pickup_time", 1, 10))
    with_date.write.format("parquet").mode("overwrite").partitionBy("date").save(output_path)


# ---- Test harness ----
if __name__ == "__main__":
    import tempfile
    import os

    spark = SparkSession.builder.appName("Test").master("local[*]").getOrCreate()

    tmp = tempfile.mkdtemp()
    csv_path = os.path.join(tmp, "trips.csv")
    with open(csv_path, "w") as fh:
        fh.write("trip_id,city,driver_id,rider_id,fare,distance_miles,pickup_time\n")
        fh.write("t1,SF,d1,r1,12.5,5.2,2024-01-15 08:30:00\n")
        fh.write("t2,NYC,d2,r2,22.0,8.1,2024-01-15 09:15:00\n")
        fh.write("t3,SF,d1,r3,8.75,3.0,2024-01-16 10:00:00\n")

    out_path = os.path.join(tmp, "trips_parquet")
    ingest_trips_to_parquet(spark, csv_path, out_path)

    result = spark.read.parquet(out_path)
    assert result.count() == 3, f"Expected 3 rows, got {result.count()}"
    assert "date" in result.columns, "Missing date column"
    dates = [r.date for r in result.select("date").distinct().collect()]
    assert "2024-01-15" in dates and "2024-01-16" in dates
    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
