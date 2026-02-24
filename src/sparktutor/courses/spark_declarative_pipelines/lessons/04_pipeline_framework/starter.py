"""
Pipeline Framework - Starter Code

Complete the Pipeline class below. You need to implement:
1. materialized_view() -- decorator that registers functions
2. _detect_deps()      -- inspect function source for spark.table() calls
3. _topo_sort()        -- topological sort using Kahn's algorithm
4. run()               -- build graph, sort, execute in order

Test your implementation by running this file. The expected output is:
  Materialized: bronze_orders (... rows)
  Materialized: silver_orders (... rows)
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
        # TODO: implement
        pass

    def _detect_deps(self, func):
        """Return a list of table names referenced via spark.table('...') in func."""
        # TODO: implement
        pass

    def _topo_sort(self, graph):
        """
        Topological sort using Kahn's algorithm.
        graph: dict mapping node_name -> list of dependency names
        Returns: list of node names in execution order
        Raises ValueError if a cycle is detected.
        """
        # TODO: implement
        pass

    def run(self):
        """Build the dependency graph, sort, and execute each flow in order."""
        # TODO: implement
        pass


# ---- Test harness (do not modify below this line) ----
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
