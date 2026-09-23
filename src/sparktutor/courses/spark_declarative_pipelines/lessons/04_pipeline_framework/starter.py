"""
Pipeline 框架 - 起始代码

完成下面的 Pipeline 类。你需要实现：
1. materialized_view() -- 注册函数的装饰器
2. _detect_deps()      -- 检查函数源码中的 spark.table() 调用
3. _topo_sort()        -- 使用 Kahn 算法进行拓扑排序
4. run()               -- 构建图、排序、按序执行

运行此文件来测试你的实现。预期输出为：
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
        """返回一个装饰器，将被装饰的函数注册到 self._flows 中。"""
        # TODO: 实现
        pass

    def _detect_deps(self, func):
        """返回函数中通过 spark.table('...') 引用的表名列表。"""
        # TODO: 实现
        pass

    def _topo_sort(self, graph):
        """
        使用 Kahn 算法进行拓扑排序。
        graph: 字典，映射 节点名 -> 依赖名列表
        返回：按执行顺序排列的节点名列表
        如果检测到循环则抛出 ValueError。
        """
        # TODO: 实现
        pass

    def run(self):
        """构建依赖图、排序，并按顺序执行每个 flow。"""
        # TODO: 实现
        pass


# ---- 测试代码（请勿修改此行以下内容）----
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
