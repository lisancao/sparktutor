"""
Full Pipeline - Solution (Capstone)

Complete bronze -> silver -> gold pipeline using the Pipeline framework.
"""

import inspect
import re
from collections import deque
from pyspark.sql import SparkSession, functions as f, Window
from pyspark.sql.types import StructType, StructField, StringType


# ---- Pipeline Framework ----

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


# ---- Pipeline layers ----

def build_pipeline(spark, csv_path):
    """Build and return a Pipeline with bronze, silver, and gold layers."""

    pipe = Pipeline(spark)

    @pipe.materialized_view()
    def bronze_orders(spark):
        """Read raw CSV, add metadata columns, deduplicate by order_id."""
        schema = StructType([
            StructField("order_id", StringType()),
            StructField("product", StringType()),
            StructField("price", StringType()),
            StructField("quantity", StringType()),
            StructField("order_ts", StringType()),
        ])

        raw = spark.read.csv(csv_path, header=True, schema=schema)

        with_meta = (raw
            .withColumn("_ingested_at", f.current_timestamp())
            .withColumn("_source_file", f.input_file_name())
        )

        return with_meta.dropDuplicates(["order_id"])

    @pipe.materialized_view()
    def silver_orders(spark):
        """Cast types, compute total, filter nulls, extract order_hour."""
        bronze = spark.table("bronze_orders")

        typed = (bronze
            .withColumn("price", f.col("price").cast("double"))
            .withColumn("quantity", f.col("quantity").cast("int"))
        )

        with_total = typed.withColumn("total", f.col("price") * f.col("quantity"))

        clean = with_total.filter(f.col("price").isNotNull())

        enriched = clean.withColumn(
            "order_hour", f.hour(f.to_timestamp(f.col("order_ts")))
        )

        return enriched

    @pipe.materialized_view()
    def gold_product_summary(spark):
        """Aggregate by product: count, revenue, avg, rank."""
        silver = spark.table("silver_orders")

        agg_df = (silver
            .groupBy("product")
            .agg(
                f.count("*").alias("order_count"),
                f.sum("total").alias("total_revenue"),
                f.avg("total").alias("avg_order_value"),
            )
        )

        w = Window.orderBy(f.col("total_revenue").desc())
        ranked = agg_df.withColumn("revenue_rank", f.rank().over(w))

        return ranked

    return pipe


# ---- Test harness ----
if __name__ == "__main__":
    import tempfile, os

    spark = SparkSession.builder.appName("FullPipelineTest").master("local[*]").getOrCreate()

    tmp = tempfile.mkdtemp()
    csv_path = os.path.join(tmp, "orders.csv")
    with open(csv_path, "w") as fh:
        fh.write("order_id,product,price,quantity,order_ts\n")
        fh.write("1,widget,9.99,2,2026-01-15 14:30:00\n")
        fh.write("2,gadget,24.99,1,2026-01-15 09:15:00\n")
        fh.write("3,widget,9.99,5,2026-01-15 16:00:00\n")
        fh.write("4,gizmo,4.99,10,2026-01-15 11:00:00\n")
        fh.write("5,widget,N/A,1,2026-01-15 20:00:00\n")
        fh.write("1,widget,9.99,2,2026-01-15 14:30:00\n")

    pipe = build_pipeline(spark, csv_path)
    pipe.run()

    bronze = spark.table("bronze_orders")
    assert bronze.count() == 5, f"Bronze: expected 5 rows, got {bronze.count()}"
    assert "_ingested_at" in bronze.columns, "Bronze: missing _ingested_at"

    silver = spark.table("silver_orders")
    assert silver.count() == 4, f"Silver: expected 4 rows, got {silver.count()}"
    assert "total" in silver.columns, "Silver: missing 'total'"
    assert "order_hour" in silver.columns, "Silver: missing 'order_hour'"

    gold = spark.table("gold_product_summary")
    assert gold.count() == 3, f"Gold: expected 3 products, got {gold.count()}"
    assert "revenue_rank" in gold.columns, "Gold: missing 'revenue_rank'"

    print("\nAll tests passed! Full pipeline is working end-to-end.")
    gold.show(truncate=False)
    spark.stop()
