"""
Optimization & Tuning - Solution

Demonstrate caching and partition optimization.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType
)
import random


def generate_data(n=10000):
    """Generate sample sales data."""
    departments = ["Engineering", "Marketing", "Sales", "Support", "HR"]
    regions = ["North", "South", "East", "West"]
    random.seed(42)
    return [
        (i, random.choice(departments), random.choice(regions),
         round(random.uniform(1000, 50000), 2))
        for i in range(n)
    ]


SCHEMA = StructType([
    StructField("id", IntegerType(), False),
    StructField("department", StringType(), False),
    StructField("region", StringType(), False),
    StructField("revenue", DoubleType(), False),
])


def optimize_pipeline(spark):
    """Demonstrate caching and partition optimization."""

    spark.conf.set("spark.sql.shuffle.partitions", "8")

    sales_df = spark.createDataFrame(generate_data(), SCHEMA)

    agg_df = (sales_df
        .groupBy("department", "region")
        .agg(
            f.sum("revenue").alias("total_revenue"),
            f.avg("revenue").alias("avg_revenue"),
        ))

    agg_df.cache()
    agg_df.count()  # trigger materialization

    top_dept = (agg_df
        .groupBy("department")
        .agg(f.sum("total_revenue").alias("dept_revenue"))
        .orderBy(f.col("dept_revenue").desc()))

    top_region = (agg_df
        .groupBy("region")
        .agg(f.avg("avg_revenue").alias("region_avg_revenue"))
        .orderBy(f.col("region_avg_revenue").desc()))

    partitions_before = agg_df.rdd.getNumPartitions()

    agg_df.unpersist()

    top_dept_single = top_dept.coalesce(1)

    return {
        "top_dept": top_dept_single,
        "top_region": top_region,
        "agg_partitions": partitions_before,
    }


# ---- Test harness ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("OptimizationTest")
        .master("local[*]")
        .getOrCreate())

    result = optimize_pipeline(spark)
    assert result is not None, "Function returned None"
    assert result["top_dept"] is not None, "top_dept is None"
    assert result["top_region"] is not None, "top_region is None"
    assert result["top_dept"].count() > 0, "top_dept is empty"
    assert result["top_region"].count() > 0, "top_region is empty"
    assert result["top_dept"].rdd.getNumPartitions() == 1, "top_dept should be 1 partition"
    print(f"Aggregation partitions: {result['agg_partitions']}")
    print("Top departments by total revenue:")
    result["top_dept"].show()
    print("Top regions by avg revenue:")
    result["top_region"].show()
    print("All tests passed!")
    spark.stop()
