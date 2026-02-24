"""
Pipeline Framework - Solution

A complete, working Pipeline class with decorator registration,
dependency detection, topological sort, and execution.
"""

import inspect
import re
from collections import deque


class Pipeline:
    def __init__(self, spark):
        self.spark = spark
        self._flows = {}

    def materialized_view(self):
        """Return a decorator that registers the wrapped function in self._flows."""
        def decorator(func):
            self._flows[func.__name__] = func
            return func
        return decorator

    def _detect_deps(self, func):
        """Return a list of table names referenced via spark.table('...') in func."""
        source = inspect.getsource(func)
        return re.findall(r'spark\.table\(["\'](\w+)["\']\)', source)

    def _topo_sort(self, graph):
        """
        Topological sort using Kahn's algorithm.
        graph: dict mapping node_name -> list of dependency names
        Returns: list of node names in execution order
        Raises ValueError if a cycle is detected.
        """
        in_degree = {n: 0 for n in graph}
        for node, deps in graph.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[node] += 1

        queue = deque(n for n, d in in_degree.items() if d == 0)
        order = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for candidate, deps in graph.items():
                if node in deps:
                    in_degree[candidate] -= 1
                    if in_degree[candidate] == 0:
                        queue.append(candidate)

        if len(order) != len(graph):
            raise ValueError("Cycle detected in pipeline dependencies")
        return order

    def run(self):
        """Build the dependency graph, sort, and execute each flow in order."""
        # Build dependency graph
        graph = {}
        for name, func in self._flows.items():
            graph[name] = self._detect_deps(func)

        # Sort
        order = self._topo_sort(graph)

        # Execute
        for name in order:
            df = self._flows[name](self.spark)
            df.createOrReplaceTempView(name)
            print(f"Materialized: {name} ({df.count()} rows)")


# ---- Test harness ----
if __name__ == "__main__":
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName("PipelineTest").master("local[*]").getOrCreate()
    pipe = Pipeline(spark)

    @pipe.materialized_view()
    def bronze_orders(spark):
        data = [("1", "widget", 9.99, 2), ("2", "gadget", 24.99, 1)]
        return spark.createDataFrame(data, ["order_id", "product", "price", "qty"])

    @pipe.materialized_view()
    def silver_orders(spark):
        from pyspark.sql import functions as f
        df = spark.table("bronze_orders")
        return df.withColumn("total", f.col("price") * f.col("qty"))

    pipe.run()
    spark.stop()
