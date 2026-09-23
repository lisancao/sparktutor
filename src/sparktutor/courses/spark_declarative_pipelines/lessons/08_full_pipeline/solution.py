"""
完整 Pipeline - 参考答案（毕业项目）

使用 Pipeline 框架完成 bronze -> silver -> gold 流水线。
"""

import inspect
import re
from collections import deque
from pyspark.sql import SparkSession, functions as f, Window
from pyspark.sql.types import StructType, StructField, StringType


# ---- Pipeline 框架 ----

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
            raise ValueError("检测到循环")
        return order

    def run(self):
        graph = {name: self._detect_deps(func) for name, func in self._flows.items()}
        order = self._topo_sort(graph)
        for name in order:
            df = self._flows[name](self.spark)
            df.createOrReplaceTempView(name)
            print(f"已物化：{name}（{df.count()} 行）")


# ---- 流水线层 ----

def build_pipeline(spark, csv_path):
    """构建并返回包含 bronze、silver 和 gold 层的 Pipeline。"""

    pipe = Pipeline(spark)

    @pipe.materialized_view()
    def bronze_orders(spark):
        """读取原始 CSV，添加元数据列，按 order_id 去重。"""
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
        """类型转换，计算 total，过滤 null，提取 order_hour。"""
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
        """按 product 聚合：count、revenue、avg、排名。"""
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


# ---- 测试代码 ----
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
    assert bronze.count() == 5, f"Bronze：预期 5 行，实际得到 {bronze.count()}"
    assert "_ingested_at" in bronze.columns, "Bronze：缺少 _ingested_at"

    silver = spark.table("silver_orders")
    assert silver.count() == 4, f"Silver：预期 4 行（过滤掉 1 个 null），实际得到 {silver.count()}"
    assert "total" in silver.columns, "Silver：缺少 'total'"
    assert "order_hour" in silver.columns, "Silver：缺少 'order_hour'"

    gold = spark.table("gold_product_summary")
    assert gold.count() == 3, f"Gold：预期 3 个产品，实际得到 {gold.count()}"
    assert "revenue_rank" in gold.columns, "Gold：缺少 'revenue_rank'"

    print("\n所有测试通过！完整流水线端到端运行正常。")
    gold.show(truncate=False)
    spark.stop()
