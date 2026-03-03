"""
Built-in Data Sources - Solution

Complete data pipeline: create, write to Parquet, read back,
create SQL view, and query.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType
)


FLIGHT_DATA = [
    ("SFO", "JFK", 45), ("SFO", "JFK", 60), ("SFO", "LAX", 10),
    ("SFO", "LAX", 15), ("SFO", "ORD", 90), ("SFO", "ORD", 30),
    ("SFO", "SEA", 5),  ("SFO", "SEA", 20), ("SFO", "DEN", 35),
]

SCHEMA = StructType([
    StructField("origin", StringType(), False),
    StructField("destination", StringType(), False),
    StructField("delay", IntegerType(), False),
])


def data_pipeline(spark, output_path):
    """Read, write, and query flight data."""

    flights_df = spark.createDataFrame(FLIGHT_DATA, SCHEMA)

    flights_df.write.mode("overwrite").parquet(output_path)

    parquet_df = spark.read.parquet(output_path)

    parquet_df.createOrReplaceTempView("flights")

    result = spark.sql("""
        SELECT destination, SUM(delay) AS total_delay
        FROM flights
        GROUP BY destination
        ORDER BY total_delay DESC
        LIMIT 3
    """)

    return result


# ---- Test harness ----
if __name__ == "__main__":
    import tempfile, os, shutil

    spark = (SparkSession.builder
        .appName("DataSourcesTest")
        .master("local[*]")
        .getOrCreate())

    tmp = tempfile.mkdtemp()
    out_path = os.path.join(tmp, "flights_parquet")

    try:
        df = data_pipeline(spark, out_path)
        assert df is not None, "Function returned None"
        assert df.count() == 3, f"Expected 3 rows, got {df.count()}"
        cols = [c.lower() for c in df.columns]
        assert "destination" in cols, f"Missing destination column, got {cols}"
        assert "total_delay" in cols, f"Missing total_delay column, got {cols}"
        top = df.collect()[0]
        assert top.destination == "ORD", f"Expected ORD as top destination, got {top.destination}"
        print("All tests passed!")
        df.show(truncate=False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        spark.stop()
