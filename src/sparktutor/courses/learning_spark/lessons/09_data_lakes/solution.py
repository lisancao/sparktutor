# spark-connectors: delta
"""
Data Lakes & Lakehouses - Solution

Build a real Delta Lake table, change it with MERGE and DELETE, then use the
transaction log: time travel, table history and the change data feed.
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

    # Version 0: the initial rows, with the change data feed switched on
    (spark.createDataFrame(INITIAL_DATA, SCHEMA)
        .write.format("delta")
        .option("delta.enableChangeDataFeed", "true")
        .save(path))

    # Version 1: upsert the raise and the new hires in one atomic commit
    spark.createDataFrame(UPDATES, SCHEMA).createOrReplaceTempView("updates")
    spark.sql(f"""
        MERGE INTO {table} t
        USING updates s
        ON t.id = s.id
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)

    # Version 2: Charlie leaves
    spark.sql(f"DELETE FROM {table} WHERE id = 3")

    current = spark.read.format("delta").load(path)
    version_0 = spark.read.format("delta").option("versionAsOf", 0).load(path)
    history = [
        (r["version"], r["operation"])
        for r in spark.sql(f"DESCRIBE HISTORY {table}").orderBy("version").collect()
    ]
    changes = (spark.read.format("delta")
        .option("readChangeFeed", "true")
        .option("startingVersion", 1)
        .load(path))

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
