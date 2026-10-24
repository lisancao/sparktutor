"""
Optimization & Tuning - Starter Code

Implement the `optimize_pipeline` function that:
1. Sets shuffle partitions to 8
2. Creates the sample sales DataFrame (10000 rows)
3. Aggregates by department and region (simulating an expensive operation)
4. Caches the aggregated result (it will be reused) and materializes it
5. Records the storage level while it is cached
6. Computes two different analyses from the cached DataFrame
7. Runs the region analysis, then captures its plan so AQE has finalized it
8. Unpersists the cache when done
9. Coalesces the department result to 1 partition for output
10. Returns a dict with the results, storage level, and plan

This exercise covers caching strategy, partition management, and AQE.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType
)
import contextlib
import io
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


def plan_text(df, mode="simple"):
    """Return what df.explain(mode) prints (works in Classic and Connect)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        df.explain(mode=mode)
    return buf.getvalue()


def partition_count(df):
    """Count non-empty partitions without the RDD API (Connect-safe)."""
    return df.select(f.spark_partition_id()).distinct().count()


def optimize_pipeline(spark):
    """Demonstrate caching, partition optimization, and AQE."""

    # TODO: Set spark.sql.shuffle.partitions to 8
    # Your code here

    sales_df = spark.createDataFrame(generate_data(), SCHEMA)

    # TODO: Aggregate by department and region: sum(revenue) AS total_revenue
    #       and avg(revenue) AS avg_revenue. This is the expensive step.
    agg_df = None  # Replace

    # TODO: Cache agg_df and trigger materialization with an action
    # Your code here

    # TODO: Record the storage level while cached: str(agg_df.storageLevel)
    storage_level = None  # Replace

    # TODO: Analysis 1: total revenue per department (sum of total_revenue),
    #       column "dept_revenue", ordered descending
    top_dept = None  # Replace

    # TODO: Analysis 2: average revenue per region (avg of avg_revenue),
    #       column "region_avg_revenue", ordered descending
    top_region = None  # Replace

    # TODO: Run top_region (e.g. collect()), THEN capture plan_text(top_region)
    region_plan = None  # Replace

    # TODO: Unpersist the cached DataFrame
    # Your code here

    # TODO: Coalesce top_dept to 1 partition
    top_dept_single = None  # Replace

    return {
        "top_dept": top_dept_single,
        "top_region": top_region,
        "storage_level": storage_level,
        "region_plan": region_plan,
    }


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("OptimizationTest")
        .master("local[*]")
        .getOrCreate())

    result = optimize_pipeline(spark)
    assert result is not None, "Function returned None"
    for key in ["top_dept", "top_region", "storage_level", "region_plan"]:
        assert result.get(key) is not None, f"{key} is missing or None"

    assert spark.conf.get("spark.sql.shuffle.partitions") == "8", "Shuffle partitions should be 8"
    assert result["top_dept"].count() == 5, "Expected 5 departments"
    assert result["top_region"].count() == 4, "Expected 4 regions"
    assert partition_count(result["top_dept"]) == 1, "top_dept should be coalesced to 1 partition"
    assert "Memory" in result["storage_level"], \
        f"agg_df should have been cached in memory, got {result['storage_level']}"
    assert "isFinalPlan=true" in result["region_plan"], \
        "Capture the region plan after running the query so AQE has finalized it"
    assert "InMemoryTableScan" in result["region_plan"], \
        "The region analysis should read from the cached aggregation"

    print(f"Storage level while cached: {result['storage_level']}")
    print("Top departments by total revenue:")
    result["top_dept"].show()
    print("Top regions by avg revenue:")
    result["top_region"].show()
    print("Region plan after execution (AQE final plan):")
    print(result["region_plan"])
    print("All tests passed!")
    spark.stop()