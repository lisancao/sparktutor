"""
Pipeline Orchestration (Starter)

Implement run_shopstream_pipeline(spark, clicks_path) that orchestrates
bronze_clicks, silver_clicks, and a gold step with error handling.
"""

import re
import inspect
from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType


class Pipeline:
    def __init__(self, spark):
        self.spark = spark
        self.steps = []

    def materialized_view(self, name):
        def decorator(func):
            self.steps.append((name, func))
            return func
        return decorator

    def _get_dependencies(self, func):
        try:
            src = inspect.getsource(func)
            return re.findall(r'spark\.table\s*\(\s*["\'](\w+)["\']\s*\)', src)
        except (TypeError, OSError):
            return []

    def _topological_order(self):
        name_to_step = {name: func for name, func in self.steps}
        deps = {name: set(self._get_dependencies(func)) for name, func in self.steps}
        order = []
        remaining = set(name_to_step.keys())
        while remaining:
            ready = [n for n in remaining if not (deps[n] & remaining)]
            if not ready:
                raise ValueError("Cycle in dependencies")
            for n in ready:
                order.append(n)
                remaining.remove(n)
        return order

    def run(self):
        # TODO: Execute steps in order with try/except
        # TODO: Return report: [{"step": name, "status": "ok"|"failed", "rows": int, "error": str|None}, ...]
        return []


def bronze_clicks(spark, csv_path):
    schema = StructType([
        StructField("event_id", StringType()),
        StructField("user_id", StringType()),
        StructField("product_id", StringType()),
        StructField("event_type", StringType()),
        StructField("timestamp", StringType()),
    ])
    raw = (spark.read.csv(csv_path, header=True, schema=schema)
        .withColumn("_ingested_at", f.current_timestamp())
        .withColumn("_source_file", f.input_file_name()))
    return raw.dropDuplicates(["event_id"])


def silver_clicks(spark, bronze_df):
    with_cast = bronze_df.withColumn("_ts_cast", f.to_timestamp(f.col("timestamp")))
    valid = with_cast.filter(f.col("_ts_cast").isNotNull()).withColumn("timestamp", f.col("_ts_cast")).drop("_ts_cast")
    return valid


def run_shopstream_pipeline(spark, clicks_path):
    """
    Run bronze -> silver -> gold pipeline. Return report.
    """
    # TODO: Create Pipeline, register bronze_clicks, silver_clicks, gold step
    # TODO: gold aggregates silver by date and event_type (count)
    # TODO: Run with error handling, return report
    return []


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    import tempfile
    import os

    spark = SparkSession.builder.appName("Orchestrate").master("local[*]").getOrCreate()

    tmp = tempfile.mkdtemp()
    csv_path = os.path.join(tmp, "clicks.csv")
    with open(csv_path, "w") as fh:
        fh.write("event_id,user_id,product_id,event_type,timestamp\n")
        fh.write("e1,u1,p1,click,2024-01-15 10:00:00\n")
        fh.write("e2,u2,p2,view,2024-01-15 10:01:00\n")

    report = run_shopstream_pipeline(spark, csv_path)
    assert len(report) == 3, f"Expected 3 steps, got {len(report)}"
    assert all(r["status"] == "ok" for r in report), f"Some steps failed: {report}"
    assert report[0]["rows"] == 2
    print("All tests passed!")
    spark.stop()
