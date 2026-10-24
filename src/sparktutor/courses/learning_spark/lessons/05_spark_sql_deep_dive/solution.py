"""
Spark SQL Deep Dive - Solution

One query written with the DataFrame API, standard SQL, and SQL pipe
syntax, plus a QUALIFY query and plans captured without touching the JVM.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType
)
import contextlib
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


def plan_text(df, mode="simple"):
    """Return what df.explain(mode) prints, as a string.

    explain() prints in both Spark Classic and Spark Connect, so capturing
    stdout works everywhere (df._jdf does not exist under Connect).
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        df.explain(mode=mode)
    return buf.getvalue()


def compare_plans(spark):
    """Write one query with the DataFrame API, SQL, and pipe syntax."""

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

    pipe_result = spark.sql("""
        FROM employees
        |> WHERE salary > 50000
        |> AGGREGATE AVG(salary) AS avg_salary GROUP BY department
        |> ORDER BY avg_salary DESC
    """)

    df_plan = plan_text(df_result)
    sql_plan = plan_text(sql_result)

    top_earners = spark.sql("""
        SELECT department, name, salary
        FROM employees
        QUALIFY ROW_NUMBER() OVER (PARTITION BY department ORDER BY salary DESC) = 1
    """)

    return {
        "df_result": df_result,
        "sql_result": sql_result,
        "pipe_result": pipe_result,
        "df_plan": df_plan,
        "sql_plan": sql_plan,
        "top_earners": top_earners,
    }


# ---- Test harness ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("SQLDeepDiveTest")
        .master("local[*]")
        .getOrCreate())

    result = compare_plans(spark)
    assert result is not None, "Function returned None"
    for key in ["df_result", "sql_result", "pipe_result", "df_plan", "sql_plan", "top_earners"]:
        assert result.get(key) is not None, f"{key} is missing or None"

    def rows(df):
        return [(r["department"], round(r["avg_salary"], 2)) for r in df.collect()]

    expected = [("Engineering", 95666.67), ("Sales", 63500.0), ("Marketing", 59000.0)]
    assert rows(result["df_result"]) == expected, f"DataFrame API result wrong: {rows(result['df_result'])}"
    assert rows(result["sql_result"]) == expected, f"SQL result wrong: {rows(result['sql_result'])}"
    assert rows(result["pipe_result"]) == expected, f"Pipe syntax result wrong: {rows(result['pipe_result'])}"

    for key in ["df_plan", "sql_plan"]:
        assert "HashAggregate" in result[key], f"{key} should contain a HashAggregate node"

    top = {r["department"]: r["name"] for r in result["top_earners"].collect()}
    assert top == {"Engineering": "Eve", "Marketing": "Charlie", "Sales": "Grace"}, \
        f"QUALIFY result wrong: {top}"

    print("DataFrame API result:")
    result["df_result"].show()
    print("Pipe syntax result:")
    result["pipe_result"].show()
    print("Top earner per department (QUALIFY):")
    result["top_earners"].orderBy("department").show()
    print("SQL physical plan:")
    print(result["sql_plan"])
    print("All tests passed!")
    spark.stop()
