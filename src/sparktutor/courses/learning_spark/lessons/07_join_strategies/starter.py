"""
Join 策略 - 起始代码

实现 `join_comparison` 函数：
1. 创建 "users" DataFrame（1000 行：user_id, name, city）
2. 创建 "orders" DataFrame（5000 行：order_id, user_id, amount）
3. 执行广播 join（对 users 表使用广播提示）
4. 执行排序合并 join（禁用广播阈值）
5. 返回两种结果及其 explain 计划字符串

本练习演示不同 join 策略之间的差异。
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType
)
import random


def generate_users(n=1000):
    """生成示例用户数据。"""
    cities = ["New York", "San Francisco", "Chicago", "Seattle", "Austin"]
    random.seed(42)
    return [(i, f"user_{i}", random.choice(cities)) for i in range(n)]


def generate_orders(n=5000, max_user_id=1000):
    """生成示例订单数据。"""
    random.seed(99)
    return [
        (i, random.randint(0, max_user_id - 1), round(random.uniform(10, 500), 2))
        for i in range(n)
    ]


USER_SCHEMA = StructType([
    StructField("user_id", IntegerType(), False),
    StructField("name", StringType(), False),
    StructField("city", StringType(), False),
])

ORDER_SCHEMA = StructType([
    StructField("order_id", IntegerType(), False),
    StructField("user_id", IntegerType(), False),
    StructField("amount", DoubleType(), False),
])


def join_comparison(spark):
    """比较广播 join 与排序合并 join。"""

    users_df = spark.createDataFrame(generate_users(), USER_SCHEMA)
    orders_df = spark.createDataFrame(generate_orders(), ORDER_SCHEMA)

    # TODO: 广播 join — 使用广播提示将 orders 与 users 连接
    broadcast_result = None  # 替换

    # 获取广播 join 的执行计划
    broadcast_plan = broadcast_result._jdf.queryExecution().simpleString()

    # TODO: 排序合并 join — 将广播阈值设为 -1 来禁用广播，
    #       然后将 orders 与 users 连接（不使用广播提示）
    # 在此设置配置
    smj_result = None  # 替换

    # 获取排序合并 join 的执行计划
    smj_plan = smj_result._jdf.queryExecution().simpleString()

    # TODO: 将阈值恢复为默认值（10MB = 10485760）
    # 在此编写代码

    return {
        "broadcast_result": broadcast_result,
        "smj_result": smj_result,
        "broadcast_plan": broadcast_plan,
        "smj_plan": smj_plan,
    }


# ---- 测试代码（请勿修改此行以下内容）----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("JoinTest")
        .master("local[*]")
        .getOrCreate())

    result = join_comparison(spark)
    assert result is not None, "函数返回了 None"
    bc_count = result["broadcast_result"].count()
    smj_count = result["smj_result"].count()
    assert bc_count == smj_count, f"行数不同：broadcast={bc_count}, smj={smj_count}"
    assert bc_count == 5000, f"预期 5000 行，实际得到 {bc_count}"
    assert "Broadcast" in result["broadcast_plan"] or "broadcast" in result["broadcast_plan"].lower(), \
        "广播计划应提及 broadcast"
    print(f"两种 join 均产生 {bc_count} 行")
    print(f"\n广播计划包含 'broadcast'：{'broadcast' in result['broadcast_plan'].lower()}")
    print(f"SMJ 计划包含 'SortMerge' 或 'sort'：{'sort' in result['smj_plan'].lower()}")
    print("所有测试通过！")
    spark.stop()
