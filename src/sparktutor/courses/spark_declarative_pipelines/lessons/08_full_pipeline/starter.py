"""
Full Pipeline - Starter Code (Capstone)

Build a complete bronze -> silver -> gold pipeline using the Pipeline
framework. Implement all three layer functions and register them with
the pipeline decorator.

The pipeline should:
  bronze_orders: Read CSV, add _ingested_at, deduplicate by order_id
  silver_orders: Cast types, add total, filter null prices, add order_hour
  gold_product_summary: groupBy product, agg count/sum/avg, rank by revenue
"""

import inspect
import re
from collections import deque
from pyspark.sql import SparkSession, functions as f, Window


# ---- Pipeline Framework (provided) ----

class Pipeline:
    def __init__(self, spark):
        self.spark = spark
        self._flows = {}

    def materialized_view(self):
        def decorator(func):
            self._flows[func.__name__] = func
            return func
        return decorator

    def _detect_deps(self, func):
        source = inspect.getsource(func)
        return re.findall(r'spark\.table\(["\'](\w+)["\']\)', source)

    def _topo_sort(self, graph):
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
            raise ValueError("Cycle detected")
        return order

    def run(self):
        graph = {name: self._detect_deps(func) for name, func in self._flows.items()}
        order = self._topo_sort(graph)
        for name in order:
            df = self._flows[name](self.spark)
            df.createOrReplaceTempView(name)
            print(f"Materialized: {name} ({df.count()} rows)")


# ---- Your pipeline layers ----

def build_pipeline(spark, csv_path):
    """Build and return a Pipeline with bronze, silver, and gold layers."""

    pipe = Pipeline(spark)

    @pipe.materialized_view()
    def bronze_orders(spark):
        """Read raw CSV, add metadata columns, deduplicate by order_id."""
        # TODO: implement
        pass

    @pipe.materialized_view()
    def silver_orders(spark):
        """Cast types, compute total, filter nulls, extract order_hour."""
        # TODO: implement
        # Read from spark.table("bronze_orders")
        pass

    @pipe.materialized_view()
    def gold_product_summary(spark):
        """Aggregate by product: count, revenue, avg, rank."""
        # TODO: implement
        # Read from spark.table("silver_orders")
        pass

    return pipe


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    import tempfile, os

    spark = SparkSession.builder.appName("FullPipelineTest").master("local[*]").getOrCreate()

    # Create test CSV
    tmp = tempfile.mkdtemp()
    csv_path = os.path.join(tmp, "orders.csv")
    with open(csv_path, "w") as fh:
        fh.write("order_id,product,price,quantity,order_ts\n")
        fh.write("1,widget,9.99,2,2026-01-15 14:30:00\n")
        fh.write("2,gadget,24.99,1,2026-01-15 09:15:00\n")
        fh.write("3,widget,9.99,5,2026-01-15 16:00:00\n")
        fh.write("4,gizmo,4.99,10,2026-01-15 11:00:00\n")
        fh.write("5,widget,N/A,1,2026-01-15 20:00:00\n")  # bad price
        fh.write("1,widget,9.99,2,2026-01-15 14:30:00\n")  # duplicate

    pipe = build_pipeline(spark, csv_path)
    pipe.run()

    # Verify bronze
    bronze = spark.table("bronze_orders")
    assert bronze.count() == 5, f"Bronze: expected 5 rows, got {bronze.count()}"
    assert "_ingested_at" in bronze.columns, "Bronze: missing _ingested_at"

    # Verify silver
    silver = spark.table("silver_orders")
    assert silver.count() == 4, f"Silver: expected 4 rows (1 null filtered), got {silver.count()}"
    assert "total" in silver.columns, "Silver: missing 'total'"
    assert "order_hour" in silver.columns, "Silver: missing 'order_hour'"

    # Verify gold
    gold = spark.table("gold_product_summary")
    assert gold.count() == 3, f"Gold: expected 3 products, got {gold.count()}"
    assert "revenue_rank" in gold.columns, "Gold: missing 'revenue_rank'"

    print("\nAll tests passed! Full pipeline is working end-to-end.")
    gold.show(truncate=False)
    spark.stop()
