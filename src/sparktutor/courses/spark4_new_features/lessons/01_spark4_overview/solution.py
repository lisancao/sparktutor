"""
Version-Aware SparkSession Factory — Solution

Creates SparkSession and detects Spark 4 for migration-aware configuration.
"""

from pyspark.sql import SparkSession


def create_spark_session():
    """
    Create a SparkSession and detect Spark version.
    Returns (spark, is_spark4) where is_spark4 is True if runtime is Spark 4+.
    """
    spark = (
        SparkSession.builder
        .appName("ECommerceMigration")
        .master("local[*]")
        .getOrCreate()
    )
    major = int(spark.version.split(".")[0])
    is_spark4 = major >= 4
    return (spark, is_spark4)


# ---- Test harness ----
if __name__ == "__main__":
    spark, is_spark4 = create_spark_session()
    assert spark is not None, "Function returned None for spark"
    major = int(spark.version.split(".")[0])
    expected_spark4 = major >= 4
    assert is_spark4 == expected_spark4, f"Expected is_spark4={expected_spark4}, got {is_spark4}"
    assert spark.appName == "ECommerceMigration", f"Expected appName ECommerceMigration, got {spark.appName}"
    print(f"Spark {spark.version} — is_spark4={is_spark4}")
    spark.stop()
