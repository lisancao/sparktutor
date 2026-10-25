# spark-connectors: delta
"""
Data Lakes & Lakehouses - Starter Code

Implement `delta_lakehouse(spark, path)` with a real Delta Lake table:
1. Write INITIAL_DATA to `path` as a Delta table with the change data feed
   enabled (version 0)
2. MERGE UPDATES into it: update matching ids, insert new ones (version 1)
3. DELETE the employee with id 3 (version 2)
4. Read the current table, and version 0 with time travel
5. Collect DESCRIBE HISTORY as (version, operation) pairs
6. Read the change data feed starting at version 1

The first line asks SparkTutor to add Delta Lake 4.4.1 to Spark (see the
lesson for doing the same yourself).
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType
)


INITIAL_DATA = [
    (1, "Alice", "Engineering", 85000.0),
    (2, "Bob", "Marketing", 65000.0),
    (3, "Charlie", "Sales", 55000.0),
]

# Applied in one MERGE: Bob's raise plus two new hires
UPDATES = [
    (2, "Bob", "Marketing", 72000.0),
    (4, "Diana", "Engineering", 92000.0),
    (5, "Eve", "Marketing", 70000.0),
]

SCHEMA = StructType([
    StructField("id", IntegerType(), False),
    StructField("name", StringType(), False),
    StructField("department", StringType(), False),
    StructField("salary", DoubleType(), False),
])


def delta_lakehouse(spark, path):
    """Create, change and inspect a Delta table stored at `path`."""
    table = f"delta.`{path}`"

    # TODO 1 (version 0): write INITIAL_DATA (with SCHEMA) to path in Delta
    #   format, with the option delta.enableChangeDataFeed set to "true"

    # TODO 2 (version 1): register UPDATES as a temp view named "updates",
    #   then MERGE INTO {table} t USING updates s ON t.id = s.id,
    #   updating all columns when matched and inserting when not matched

    # TODO 3 (version 2): DELETE FROM {table} WHERE id = 3

    current = None    # TODO 4: read the current table (format "delta")
    version_0 = None  # TODO 4: read version 0 (option versionAsOf)
    history = None    # TODO 5: [(version, operation), ...] from DESCRIBE HISTORY, oldest first
    changes = None    # TODO 6: the change data feed (option readChangeFeed) from version 1

    return {
        "current": current,
        "version_0": version_0,
        "history": history,
        "changes": changes,
    }


# ---- Test harness ----
if __name__ == "__main__":
    import os, tempfile, shutil

    spark = (SparkSession.builder
        .appName("LakehouseTest")
        .master("local[*]")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "employees")

    try:
        result = delta_lakehouse(spark, path)
        assert result is not None, "Function returned None"
        assert os.path.isdir(os.path.join(path, "_delta_log")), "No _delta_log: write with format('delta')"

        current = sorted((r["id"], r["salary"]) for r in result["current"].collect())
        assert current == [(1, 85000.0), (2, 72000.0), (4, 92000.0), (5, 70000.0)], (
            f"Current table should have Alice, Bob at 72000, Diana and Eve; got {current}")

        v0 = sorted((r["id"], r["salary"]) for r in result["version_0"].collect())
        assert v0 == [(1, 85000.0), (2, 65000.0), (3, 55000.0)], f"Version 0 should be the initial rows, got {v0}"

        ops = [op for _, op in result["history"]]
        assert ops == ["WRITE", "MERGE", "DELETE"], f"Expected history WRITE, MERGE, DELETE; got {ops}"

        changes = result["changes"]
        for col_name in ["_change_type", "_commit_version", "_commit_timestamp"]:
            assert col_name in changes.columns, (
                f"changes is missing {col_name}: read with format('delta') and readChangeFeed")
        got = sorted((r["id"], r["_change_type"], r["_commit_version"]) for r in changes.collect())
        expected = [
            (2, "update_postimage", 1), (2, "update_preimage", 1),
            (3, "delete", 2), (4, "insert", 1), (5, "insert", 1),
        ]
        assert got == expected, f"Expected changes {expected}, got {got}"

        print("Current table:")
        result["current"].orderBy("id").show()
        print("Version 0 (time travel):")
        result["version_0"].orderBy("id").show()
        print("History:", result["history"])
        print("Change data feed from version 1:")
        (changes.select("id", "name", "salary", "_change_type", "_commit_version")
            .orderBy("_commit_version", "id", "_change_type").show())
        print("All tests passed!")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        spark.stop()
