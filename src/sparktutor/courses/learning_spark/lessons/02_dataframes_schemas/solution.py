"""
DataFrames and Schemas - Solution

Complete DataFrame creation with explicit schema, complex types,
and computed columns.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, ArrayType
)


DATA = [
    [1, "Jules", "Damji", "https://tinyurl.1", "1/4/2016", 4535, ["twitter", "LinkedIn"]],
    [2, "Brooke", "Wenig", "https://tinyurl.2", "5/5/2018", 8908, ["twitter", "LinkedIn"]],
    [3, "Denny", "Lee", "https://tinyurl.3", "6/7/2019", 7659, ["web", "twitter", "FB", "LinkedIn"]],
    [4, "Tathagata", "Das", "https://tinyurl.4", "5/12/2018", 10568, ["twitter", "FB"]],
    [5, "Matei", "Zaharia", "https://tinyurl.5", "5/14/2014", 40578, ["web", "twitter", "FB", "LinkedIn"]],
    [6, "Reynold", "Xin", "https://tinyurl.6", "3/2/2015", 25568, ["twitter", "LinkedIn"]],
]


def build_blogs_df(spark):
    """Create a blogs DataFrame with schema, data, and computed column."""

    schema = StructType([
        StructField("Id", IntegerType(), False),
        StructField("First", StringType(), False),
        StructField("Last", StringType(), False),
        StructField("Url", StringType(), False),
        StructField("Published", StringType(), False),
        StructField("Hits", IntegerType(), False),
        StructField("Campaigns", ArrayType(StringType()), False),
    ])

    blogs_df = spark.createDataFrame(DATA, schema)

    result = blogs_df.withColumn("Big_Hitter", f.col("Hits") > 10000)

    return result


# ---- Test harness ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("BlogsTest")
        .master("local[*]")
        .getOrCreate())

    df = build_blogs_df(spark)
    assert df is not None, "Function returned None"
    assert df.count() == 6, f"Expected 6 rows, got {df.count()}"
    assert "Big_Hitter" in df.columns, "Missing Big_Hitter column"
    assert "Campaigns" in df.columns, "Missing Campaigns column"

    big_hitters = df.filter(f.col("Big_Hitter") == True).count()
    assert big_hitters == 3, f"Expected 3 big hitters, got {big_hitters}"
    print("All tests passed!")
    df.show(truncate=False)
    spark.stop()
