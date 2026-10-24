"""
Built-in Data Sources - Starter Code

Implement the `data_pipeline` function that:
1. Creates a sample DataFrame of flight data
2. Writes it to Parquet format at a given path
3. Reads the Parquet back into a new DataFrame
4. Creates a temporary SQL view called "flights"
5. Runs a SQL query to find the top 3 destinations by total delay
6. Returns the query result DataFrame

Then implement `xml_roundtrip`, which writes a DataFrame as XML (rootTag
"delays", rowTag "route") and reads it back.

This exercise covers DataFrameReader, DataFrameWriter, temp views, SQL,
and the built-in XML source.
"""

from pyspark.sql import SparkSession, functions as f, Row
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

    # TODO: Create a DataFrame from FLIGHT_DATA using SCHEMA
    flights_df = None  # Replace

    # TODO: Write the DataFrame to Parquet at output_path (overwrite mode)
    # Your code here

    # TODO: Read the Parquet back into a new DataFrame
    parquet_df = None  # Replace

    # TODO: Create a temporary view called "flights"
    # Your code here

    # TODO: Run SQL to find top 3 destinations by total delay
    #       SELECT destination, SUM(delay) AS total_delay
    #       FROM flights GROUP BY destination
    #       ORDER BY total_delay DESC LIMIT 3
    result = None  # Replace with spark.sql(...)

    return result


def xml_roundtrip(spark, df, xml_path):
    """Write df as XML and read it back (XML is built in since Spark 4.0)."""

    # TODO: Write df to xml_path as XML in overwrite mode, with
    #       rootTag "delays" and rowTag "route"
    # Your code here

    # TODO: Read xml_path back with rowTag "route"
    xml_df = None  # Replace with spark.read...

    return xml_df


# ---- Test harness (do not modify below this line) ----
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

        xml_df = xml_roundtrip(spark, df, os.path.join(tmp, "delays_xml"))
        assert xml_df is not None, "xml_roundtrip returned None"
        assert xml_df.count() == 3, f"Expected 3 XML rows, got {xml_df.count()}"
        assert set(c.lower() for c in xml_df.columns) == {"destination", "total_delay"}, \
            f"Unexpected XML columns: {xml_df.columns}"
        xml_top = xml_df.orderBy(f.col("total_delay").desc()).first()
        assert xml_top.destination == "ORD", f"XML round trip lost data: {xml_top}"

        print("All tests passed!")
        df.show(truncate=False)
        print("Read back from XML:")
        xml_df.show(truncate=False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        spark.stop()
