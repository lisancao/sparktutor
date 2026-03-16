"""
Pipeline as Code — Starter

Implement the Pipeline class with:
1. materialized_view(name) decorator
2. _get_dependencies(func) to extract spark.table() refs
3. _topological_order() for execution order
4. run() to execute steps and return report

Register step_a, step_b (reads step_a), step_c (reads step_b).
Verify execution order and row counts.
"""

import re
import inspect
from pyspark.sql import SparkSession, functions as f


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
        # TODO: Extract table names from spark.table("name") in func source
        return []

    def _topological_order(self):
        # TODO: Build dependency graph, return step names in valid order
        return [name for name, _ in self.steps]

    def run(self):
        # TODO: Execute steps in _topological_order(), register each as temp view,
        #       return [(name, row_count), ...]
        return []


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("PipelineTest").master("local[*]").getOrCreate()

    pipeline = Pipeline(spark)

    @pipeline.materialized_view("step_a")
    def step_a():
        return spark.createDataFrame([(1,), (2,), (3,)], ["x"])

    @pipeline.materialized_view("step_b")
    def step_b():
        df = spark.table("step_a")
        return df.withColumn("y", f.col("x") * 2)

    @pipeline.materialized_view("step_c")
    def step_c():
        df = spark.table("step_b")
        return df.withColumn("z", f.col("y") + 1)

    report = pipeline.run()
    assert len(report) == 3, f"Expected 3 steps, got {len(report)}"
    names = [r[0] for r in report]
    assert names == ["step_a", "step_b", "step_c"], f"Wrong order: {names}"
    assert report[0][1] == 3, f"step_a should have 3 rows, got {report[0][1]}"
    assert report[1][1] == 3, f"step_b should have 3 rows, got {report[1][1]}"
    assert report[2][1] == 3, f"step_c should have 3 rows, got {report[2][1]}"
    print("All tests passed!")
    spark.stop()
