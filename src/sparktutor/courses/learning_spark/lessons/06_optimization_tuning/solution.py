"""
Optimization & Tuning - Solution

Caching a reused aggregation, reading an AQE final plan, and coalescing
output, all with Connect-safe APIs.
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

    storage_level = str(agg_df.storageLevel)

    top_dept = (agg_df
        .groupBy("department")
        .agg(f.sum("total_revenue").alias("dept_revenue"))
        .orderBy(f.col("dept_revenue").desc()))

    top_region = (agg_df
        .groupBy("region")
        .agg(f.avg("avg_revenue").alias("region_avg_revenue"))
        .orderBy(f.col("region_avg_revenue").desc()))

    top_region.collect()  # run it so AQE finalizes the plan
    region_plan = plan_text(top_region)

    agg_df.unpersist()

    top_dept_single = top_dept.coalesce(1)

    return {
        "top_dept": top_dept_single,
        "top_region": top_region,
        "storage_level": storage_level,
        "region_plan": region_plan,
    }


# ---- Test harness ----
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