"""
Spark SQL 深入探索 - 参考答案

比较 DataFrame API 和 SQL 的执行计划。
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType
)


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

    emp_df.createOrReplaceTempView("employees")

    df_result = (emp_df
        .filter(f.col("salary") > 50000)
        .groupBy("department")
        .agg(f.avg("salary").alias("avg_salary"))
        .orderBy(f.col("avg_salary").desc()))

    sql_result = spark.sql("""
        SELECT department, AVG(salary) AS avg_salary
        FROM employees
        WHERE salary > 50000
        GROUP BY department
        ORDER BY avg_salary DESC
    """)

    df_plan = df_result._jdf.queryExecution().simpleString()
    sql_plan = sql_result._jdf.queryExecution().simpleString()

    return {
        "df_result": df_result,
        "sql_result": sql_result,
        "df_plan": df_plan,
        "sql_plan": sql_plan,
    }


# ---- 测试代码 ----
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
