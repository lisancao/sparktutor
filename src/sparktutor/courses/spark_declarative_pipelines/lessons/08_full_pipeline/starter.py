"""
完整 Pipeline - 起始代码（毕业项目）

使用 Pipeline 框架构建完整的 bronze -> silver -> gold 流水线。
实现所有三层函数并用流水线装饰器注册。

流水线应：
  bronze_orders: 读取 CSV，添加 _ingested_at，按 order_id 去重
  silver_orders: 类型转换，添加 total，过滤 null price，添加 order_hour
  gold_product_summary: 按 product 分组，聚合 count/sum/avg，按营收排名
"""

import inspect
import re
from collections import deque
from pyspark.sql import SparkSession, functions as f, Window


# ---- Pipeline 框架（已提供）----

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


# ---- 你的流水线层 ----

def build_pipeline(spark, csv_path):
    """构建并返回包含 bronze、silver 和 gold 层的 Pipeline。"""

    pipe = Pipeline(spark)

    @pipe.materialized_view()
    def bronze_orders(spark):
        """读取原始 CSV，添加元数据列，按 order_id 去重。"""
        # TODO: 实现
        pass

    @pipe.materialized_view()
    def silver_orders(spark):
        """类型转换，计算 total，过滤 null，提取 order_hour。"""
        # TODO: 实现
        # 从 spark.table("bronze_orders") 读取
        pass

    @pipe.materialized_view()
    def gold_product_summary(spark):
        """按 product 聚合：count、revenue、avg、排名。"""
        # TODO: 实现
        # 从 spark.table("silver_orders") 读取
        pass

    return pipe


# ---- 测试代码（请勿修改此行以下内容）----
if __name__ == "__main__":
    import tempfile, os

    spark = SparkSession.builder.appName("FullPipelineTest").master("local[*]").getOrCreate()

    # 创建测试 CSV 文件
    tmp = tempfile.mkdtemp()
    csv_path = os.path.join(tmp, "orders.csv")
    with open(csv_path, "w") as fh:
        fh.write("order_id,product,price,quantity,order_ts\n")
        fh.write("1,widget,9.99,2,2026-01-15 14:30:00\n")
        fh.write("2,gadget,24.99,1,2026-01-15 09:15:00\n")
        fh.write("3,widget,9.99,5,2026-01-15 16:00:00\n")
        fh.write("4,gizmo,4.99,10,2026-01-15 11:00:00\n")
        fh.write("5,widget,N/A,1,2026-01-15 20:00:00\n")  # 坏价格
        fh.write("1,widget,9.99,2,2026-01-15 14:30:00\n")  # 重复行

    pipe = build_pipeline(spark, csv_path)
    pipe.run()

    # 验证 bronze
    bronze = spark.table("bronze_orders")
    assert bronze.count() == 5, f"Bronze：预期 5 行，实际得到 {bronze.count()}"
    assert "_ingested_at" in bronze.columns, "Bronze：缺少 _ingested_at"

    # 验证 silver
    silver = spark.table("silver_orders")
    assert silver.count() == 4, f"Silver：预期 4 行（过滤掉 1 个 null），实际得到 {silver.count()}"
    assert "total" in silver.columns, "Silver：缺少 'total'"
    assert "order_hour" in silver.columns, "Silver：缺少 'order_hour'"

    # 验证 gold
    gold = spark.table("gold_product_summary")
    assert gold.count() == 3, f"Gold：预期 3 个产品，实际得到 {gold.count()}"
    assert "revenue_rank" in gold.columns, "Gold：缺少 'revenue_rank'"

    print("\n所有测试通过！完整流水线端到端运行正常。")
    gold.show(truncate=False)
    spark.stop()
