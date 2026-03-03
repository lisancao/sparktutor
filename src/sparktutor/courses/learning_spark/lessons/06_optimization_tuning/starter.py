"""
Optimization & Tuning - Starter Code

Implement the `optimize_pipeline` function that:
1. Creates a large-ish sample DataFrame (10000 rows)
2. Sets shuffle partitions to a reasonable number (e.g., 8)
3. Performs a groupBy aggregation (simulating an expensive operation)
4. Caches the aggregated result (it will be reused)
5. Computes two different analyses from the cached DataFrame
6. Unpersists the cache when done
7. Coalesces the final result to 1 partition for output
8. Returns a dict with the two analysis results and partition info

This exercise covers caching strategy and partition management.
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

    # TODO: Set shuffle partitions to 8
    # Your code here

    sales_df = spark.createDataFrame(generate_data(), SCHEMA)

    # TODO: Aggregate by department and region — sum and avg of revenue
    #       This simulates an expensive operation worth caching
    agg_df = None  # Replace

    # TODO: Cache the aggregated DataFrame and trigger materialization
    # Your code here

    # TODO: Analysis 1 — from cached agg_df, find top department by total revenue
    top_dept = None  # Replace

    # TODO: Analysis 2 — from cached agg_df, find top region by avg revenue
    top_region = None  # Replace

    # TODO: Unpersist the cached DataFrame
    # Your code here

    # TODO: Coalesce top_dept to 1 partition
    top_dept_single = None  # Replace

    partitions_before = agg_df.rdd.getNumPartitions()

    return {
        "top_dept": top_dept_single,
        "top_region": top_region,
        "agg_partitions": partitions_before,
    }


# ---- Test harness (do not modify below this line) ----
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
