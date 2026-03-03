"""
Data Lakes & Lakehouses - Solution

Simulate lakehouse versioning with Parquet directories.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType
)
import os


INITIAL_DATA = [
    (1, "Alice", "Engineering", 85000.0),
    (2, "Bob", "Marketing", 65000.0),
    (3, "Charlie", "Sales", 55000.0),
]

NEW_EMPLOYEES = [
    (4, "Diana", "Engineering", 92000.0),
    (5, "Eve", "Marketing", 70000.0),
]

SCHEMA = StructType([
    StructField("id", IntegerType(), False),
    StructField("name", StringType(), False),
    StructField("department", StringType(), False),
    StructField("salary", DoubleType(), False),
])


def lakehouse_simulation(spark, base_path):
    """Simulate lakehouse versioning with Parquet directories."""

    v0_path = os.path.join(base_path, "v0")
    v1_path = os.path.join(base_path, "v1")

    initial_df = spark.createDataFrame(INITIAL_DATA, SCHEMA)
    initial_df.write.parquet(v0_path)

    new_df = spark.createDataFrame(NEW_EMPLOYEES, SCHEMA)
    combined_df = initial_df.union(new_df)
    combined_df.write.parquet(v1_path)

    version_0 = spark.read.parquet(v0_path)
    version_1 = spark.read.parquet(v1_path)

    schemas_match = version_0.schema == version_1.schema

    return {
        "version_0": version_0,
        "version_1": version_1,
        "v0_count": version_0.count(),
        "v1_count": version_1.count(),
        "schemas_match": schemas_match,
    }


# ---- Test harness ----
if __name__ == "__main__":
    import tempfile, shutil

    spark = (SparkSession.builder
        .appName("LakehouseTest")
        .master("local[*]")
        .getOrCreate())

    tmp = tempfile.mkdtemp()
    base = os.path.join(tmp, "lakehouse")

    try:
        result = lakehouse_simulation(spark, base)
        assert result is not None, "Function returned None"
        assert result["v0_count"] == 3, f"Version 0 should have 3 rows, got {result['v0_count']}"
        assert result["v1_count"] == 5, f"Version 1 should have 5 rows, got {result['v1_count']}"
        assert result["schemas_match"] == True, "Schemas should match between versions"
        print("Version 0 (initial):")
        result["version_0"].show()
        print("Version 1 (with new employees):")
        result["version_1"].show()
        print(f"Schemas match: {result['schemas_match']}")
        print("All tests passed!")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        spark.stop()
