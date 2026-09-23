"""
Join 策略 - 参考答案

比较广播 join 与排序合并 join 策略。
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType
)
import random


def generate_users(n=1000):
    cities = ["New York", "San Francisco", "Chicago", "Seattle", "Austin"]
    random.seed(42)
    return [(i, f"user_{i}", random.choice(cities)) for i in range(n)]


def generate_orders(n=5000, max_user_id=1000):
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

    broadcast_result = orders_df.join(f.broadcast(users_df), "user_id")

    broadcast_plan = broadcast_result._jdf.queryExecution().simpleString()

    spark.conf.set("spark.sql.autoBroadcastJoinThreshold", "-1")
    smj_result = orders_df.join(users_df, "user_id")

    smj_plan = smj_result._jdf.queryExecution().simpleString()

    spark.conf.set("spark.sql.autoBroadcastJoinThreshold", "10485760")

    return {
        "broadcast_result": broadcast_result,
        "smj_result": smj_result,
        "broadcast_plan": broadcast_plan,
        "smj_plan": smj_plan,
    }


# ---- 测试代码 ----
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
