"""
Spark SQL 深入探索 - 起始代码

实现 `compare_plans` 函数：
1. 创建员工示例 DataFrame
2. 使用 DataFrame API 编写查询：筛选 salary > 50000，
   按 department 分组，计算平均薪资，按均值降序排列
3. 使用 Spark SQL 编写相同的查询
4. 返回包含 "df_plan" 和 "sql_plan" 键的字典，
   值为两种方式的 explain 字符串输出

本练习展示两种 API 产生相同的执行计划。
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType
)
import io


EMPLOYEE_DATA = [
    (1, "Alice", "Engineering", 85000.0),
    (2, "Bob", "Engineering", 92000.0),
    (3, "Charlie", "Marketing", 65000.0),
    (4, "Diana", "Marketing", 48000.0),
    (5, "Eve", "Engineering", 110000.0),
    (6, "Frank", "Sales", 55000.0),
    (7, "Grace", "Sales", 72000.0),
    (8, "Hank", "Marketing", 53000.0),
]

SCHEMA = StructType([
    StructField("id", IntegerType(), False),
    StructField("name", StringType(), False),
    StructField("department", StringType(), False),
    StructField("salary", DoubleType(), False),
])


def compare_plans(spark):
    """比较 DataFrame API 和 SQL 的执行计划。"""

    emp_df = spark.createDataFrame(EMPLOYEE_DATA, SCHEMA)

    # TODO: 注册为临时视图以便 SQL 查询
    # 在此编写代码

    # TODO: DataFrame API 方式 — 筛选 salary > 50000，
    #       按 department 分组，计算平均薪资，按均值降序
    df_result = None  # 替换

    # TODO: SQL 方式 — 使用 spark.sql() 实现与上面相同的逻辑
    sql_result = None  # 替换

    # 获取 explain 计划的字符串表示
    # （explain() 输出到 stdout；我们在这里捕获它）
    df_plan = df_result._jdf.queryExecution().simpleString()
    sql_plan = sql_result._jdf.queryExecution().simpleString()

    return {
        "df_result": df_result,
        "sql_result": sql_result,
        "df_plan": df_plan,
        "sql_plan": sql_plan,
    }


# ---- 测试代码（请勿修改此行以下内容）----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("SQLDeepDiveTest")
        .master("local[*]")
        .getOrCreate())

    result = compare_plans(spark)
    assert result is not None, "函数返回了 None"
    assert result["df_result"].count() == 3, "DataFrame API 应返回 3 个部门"
    assert result["sql_result"].count() == 3, "SQL 应返回 3 个部门"
    assert len(result["df_plan"]) > 0, "df_plan 不应为空"
    assert len(result["sql_plan"]) > 0, "sql_plan 不应为空"
    print("DataFrame API 结果：")
    result["df_result"].show()
    print("SQL 结果：")
    result["sql_result"].show()
    print("所有测试通过！")
    spark.stop()
