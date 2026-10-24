"""
DataFrames and Schemas - Starter Code

Implement the `build_blogs_df` function that:
1. Defines a schema with: Id (int), First (string), Last (string),
   Url (string), Published (string), Hits (int), Campaigns (array of strings)
2. Creates a DataFrame from the provided data using that schema
3. Uses one withColumns call to add:
   - "Big_Hitter": boolean, True when Hits > 10000
   - "Published_Date": Published (format M/d/yyyy) parsed to a DATE
4. Returns the DataFrame

Based on Example-3_6 from Learning Spark.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, ArrayType
)


# Sample blog author data
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

    # TODO: Define the schema using StructType with the columns listed above
    #       Note: Campaigns should be ArrayType(StringType())
    schema = None  # Replace with StructType(...)

    # TODO: Create the DataFrame from DATA using the schema
    blogs_df = None  # Replace with spark.createDataFrame(...)

    # TODO: Add two columns with a single withColumns({...}) call:
    #       "Big_Hitter"     -> True when Hits > 10000
    #       "Published_Date" -> f.to_date("Published", "M/d/yyyy")
    result = None  # Replace

    return result


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    import datetime
    from pyspark.sql.types import DateType

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

    assert "Published_Date" in df.columns, "Missing Published_Date column"
    assert isinstance(df.schema["Published_Date"].dataType, DateType), \
        f"Published_Date should be a DATE, got {df.schema['Published_Date'].dataType}"
    jules = df.filter(f.col("Id") == 1).select("Published_Date").first()[0]
    assert jules == datetime.date(2016, 1, 4), f"Expected 2016-01-04 for Jules, got {jules}"
    print("All tests passed!")
    df.show(truncate=False)
    spark.stop()
