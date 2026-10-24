"""
Data Lakes & Lakehouses - Starter Code

Implement the `lakehouse_simulation` function that simulates lakehouse
concepts using Parquet + versioned directories:
1. Creates initial employee data and writes it as "version 0"
2. Applies a raise and adds new employees, writing "version 1"
3. Reads both versions to demonstrate "time travel"
4. Verifies schema consistency between versions
5. Builds a change feed (inserts and deletes) between the versions, in the
   same shape as Spark 4.2's CDC rows (_change_type, _commit_version)
6. Returns a dict with both versions, schema info, and the changes

Runs on plain PySpark; no Delta/Iceberg JARs required. In production, a
table format gives you real ACID commits, and its connector can serve
spark.read.changes() directly.
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

    # TODO: Create the initial DataFrame and write it to v0_path as Parquet
    initial_df = None  # Replace
    # Write to v0_path here

    # TODO: Build version 1:
    #       - apply RAISES to initial_df (replace salary where id is in RAISES;
    #         f.when(...).otherwise(...) or a small join both work)
    #       - union the new hires (NEW_EMPLOYEES)
    #       - write the result to v1_path as Parquet
    new_df = None  # Replace
    combined_df = None  # Replace
    # Write to v1_path here

    # TODO: Read back both versions (simulating time travel)
    version_0 = None  # Replace: read from v0_path
    version_1 = None  # Replace: read from v1_path

    # TODO: Verify schema consistency
    schemas_match = None  # Replace: compare version_0.schema == version_1.schema

    # TODO: Build the change feed from v0 to v1:
    #       rows in v1 but not v0 -> _change_type "insert"
    #       rows in v0 but not v1 -> _change_type "delete"
    #       add _commit_version = 1 to every row (use exceptAll and unionByName)
    changes = None  # Replace

    return {
        "version_0": version_0,
        "version_1": version_1,
        "v0_count": version_0.count(),
        "v1_count": version_1.count(),
        "schemas_match": schemas_match,
        "changes": changes,
    }


# ---- Test harness (do not modify below this line) ----
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
