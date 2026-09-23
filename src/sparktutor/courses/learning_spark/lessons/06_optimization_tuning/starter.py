"""
优化与调优 - 起始代码

实现 `optimize_pipeline` 函数：
1. 创建一个稍大的示例 DataFrame（10000 行）
2. 将 shuffle 分区数设置为合理值（如 8）
3. 执行 groupBy 聚合（模拟耗时操作）
4. 缓存聚合结果（后续会复用）
5. 从缓存的 DataFrame 计算两种不同的分析
6. 完成后解除缓存
7. 将最终结果合并为 1 个分区用于输出
8. 返回包含两种分析结果和分区信息的字典

本练习涵盖缓存策略和分区管理。
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType
)
import random


def generate_data(n=10000):
    """生成示例销售数据。"""
    departments = ["Engineering", "Marketing", "Sales", "Support", "HR"]
    regions = ["North", "South", "East", "West"]
    random.seed(42)
    return [
        (i, random.choice(departments), random.choice(regions),
         round(random.uniform(1000, 50000), 2))
        for i in range(n)
    ]


SCHEMA = StructType([
    StructField("id", IntegerType(), False),
    StructField("department", StringType(), False),
    StructField("region", StringType(), False),
    StructField("revenue", DoubleType(), False),
])


def optimize_pipeline(spark):
    """演示缓存和分区优化。"""

    # TODO: 将 shuffle 分区数设置为 8
    # 在此编写代码

    sales_df = spark.createDataFrame(generate_data(), SCHEMA)

    # TODO: 按 department 和 region 聚合 — 对 revenue 求和和求平均值
    #       这模拟了一个值得缓存的耗时操作
    agg_df = None  # 替换

    # TODO: 缓存聚合后的 DataFrame 并触发物化
    # 在此编写代码

    # TODO: 分析 1 — 从缓存的 agg_df 中，按总营收找出排名第一的部门
    top_dept = None  # 替换

    # TODO: 分析 2 — 从缓存的 agg_df 中，按平均营收找出排名第一的区域
    top_region = None  # 替换

    # TODO: 解除缓存的 DataFrame
    # 在此编写代码

    # TODO: 将 top_dept 合并为 1 个分区
    top_dept_single = None  # 替换

    partitions_before = agg_df.rdd.getNumPartitions()

    return {
        "top_dept": top_dept_single,
        "top_region": top_region,
        "agg_partitions": partitions_before,
    }


# ---- 测试代码（请勿修改此行以下内容）----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("OptimizationTest")
        .master("local[*]")
        .getOrCreate())

    result = optimize_pipeline(spark)
    assert result is not None, "函数返回了 None"
    assert result["top_dept"] is not None, "top_dept 为 None"
    assert result["top_region"] is not None, "top_region 为 None"
    assert result["top_dept"].count() > 0, "top_dept 为空"
    assert result["top_region"].count() > 0, "top_region 为空"
    assert result["top_dept"].rdd.getNumPartitions() == 1, "top_dept 应为 1 个分区"
    print(f"聚合分区数：{result['agg_partitions']}")
    print("按总营收排名的部门：")
    result["top_dept"].show()
    print("按平均营收排名的区域：")
    result["top_region"].show()
    print("所有测试通过！")
    spark.stop()
