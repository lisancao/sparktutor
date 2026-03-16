"""
Version-Aware SparkSession Factory — Starter Code

Implement create_spark_session() that returns a SparkSession and is_spark4 boolean.
Configure for Spark 3 vs 4 as appropriate.
"""

from pyspark.sql import SparkSession


def create_spark_session():
    """
    Create a SparkSession and detect Spark version.
    Returns (spark, is_spark4) where is_spark4 is True if runtime is Spark 4+.
    """

    # TODO: Build SparkSession with appName "ECommerceMigration" and master "local[*]"
    # spark = ...

    # TODO: Parse spark.version to get major version
    # major = ...

    # TODO: Set is_spark4 = major >= 4
    # is_spark4 = ...

    # TODO: Optionally configure ANSI mode based on version
    # (Spark 4 default is ANSI on; Spark 3 default is off)

    return (None, False)


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark, is_spark4 = create_spark_session()
    assert spark is not None, "Function returned None for spark"
    major = int(spark.version.split(".")[0])
    expected_spark4 = major >= 4
    assert is_spark4 == expected_spark4, f"Expected is_spark4={expected_spark4}, got {is_spark4}"
    assert spark.appName == "ECommerceMigration", f"Expected appName ECommerceMigration, got {spark.appName}"
    print(f"Spark {spark.version} — is_spark4={is_spark4}")
    spark.stop()
