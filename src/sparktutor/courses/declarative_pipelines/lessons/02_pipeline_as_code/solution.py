"""
Pipeline as Code — Solution

Complete Pipeline class with dependency detection and topological execution.
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
            ready = [n for n in remaining if not deps[n] & remaining]
            if not ready:
                raise ValueError("Cycle detected in pipeline dependencies")
            for n in ready:
                order.append(n)
                remaining.remove(n)
        return order

    def run(self):
        name_to_step = {name: func for name, func in self.steps}
        order = self._topological_order()
        report = []
        for name in order:
            func = name_to_step[name]
            df = func()
            df.createOrReplaceTempView(name)
            count = df.count()
            report.append((name, count))
        return report


# ---- Test harness ----
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
