"""
Data Lakes & Lakehouses - Solution

Simulate lakehouse versioning with Parquet directories and derive a
CDC-shaped change feed between two versions.
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

# Salary changes applied in version 1: {employee id: new salary}
RAISES = {2: 72000.0}

SCHEMA = StructType([
    StructField("id", IntegerType(), False),
    StructField("name", StringType(), False),
    StructField("department", StringType(), False),
    StructField("salary", DoubleType(), False),
])


def lakehouse_simulation(spark, base_path):
    """Simulate lakehouse versioning and a change feed with Parquet directories."""

    v0_path = os.path.join(base_path, "v0")
    v1_path = os.path.join(base_path, "v1")

    initial_df = spark.createDataFrame(INITIAL_DATA, SCHEMA)
    initial_df.write.parquet(v0_path)

    salary = f.col("salary")
    for emp_id, new_salary in RAISES.items():
        salary = f.when(f.col("id") == emp_id, f.lit(new_salary)).otherwise(salary)
    raised_df = initial_df.withColumn("salary", salary)

    new_df = spark.createDataFrame(NEW_EMPLOYEES, SCHEMA)
    combined_df = raised_df.unionByName(new_df)
    combined_df.write.parquet(v1_path)

    version_0 = spark.read.parquet(v0_path)
    version_1 = spark.read.parquet(v1_path)

    schemas_match = version_0.schema == version_1.schema

    inserts = version_1.exceptAll(version_0).withColumn("_change_type", f.lit("insert"))
    deletes = version_0.exceptAll(version_1).withColumn("_change_type", f.lit("delete"))
    changes = (inserts.unionByName(deletes)
        .withColumn("_commit_version", f.lit(1).cast("long")))

    return {
        "version_0": version_0,
        "version_1": version_1,
        "v0_count": version_0.count(),
        "v1_count": version_1.count(),
        "schemas_match": schemas_match,
        "changes": changes,
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

        bob_v1 = result["version_1"].filter(f.col("id") == 2).first()
        assert bob_v1["salary"] == 72000.0, f"Bob's raise is missing from version 1: {bob_v1}"

        changes = result["changes"]
        assert changes is not None, "changes is None"
        for col_name in ["_change_type", "_commit_version"]:
            assert col_name in changes.columns, f"changes is missing {col_name}"
        got = sorted((r["id"], r["_change_type"]) for r in changes.collect())
        expected = [(2, "delete"), (2, "insert"), (4, "insert"), (5, "insert")]
        assert got == expected, f"Expected changes {expected}, got {got}"
        assert {r["_commit_version"] for r in changes.collect()} == {1}, "_commit_version should be 1"

        print("Version 0 (initial):")
        result["version_0"].orderBy("id").show()
        print("Version 1 (raise + new hires):")
        result["version_1"].orderBy("id").show()
        print(f"Schemas match: {result['schemas_match']}")
        print("Change feed v0 -> v1 (same shape as Spark 4.2 CDC rows):")
        changes.orderBy("id", "_change_type").show()
        print("All tests passed!")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        spark.stop()
