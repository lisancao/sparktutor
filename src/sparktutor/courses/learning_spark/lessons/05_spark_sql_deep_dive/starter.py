"""
Spark SQL Deep Dive - Starter Code

Implement the `compare_plans` function that writes one query three ways.
The query: average salary per department for employees earning more than
50000, highest average first.

1. Register the employee DataFrame as the temp view "employees"
2. DataFrame API version -> df_result
3. Standard SQL version -> sql_result
4. SQL pipe syntax version (FROM ... |> ...) -> pipe_result
5. Capture the DataFrame and SQL plans with plan_text() -> df_plan, sql_plan
6. Use QUALIFY (Spark 4.2) to keep the top earner per department
   -> top_earners with columns department, name, salary
7. Return all six in a dict

This demonstrates that every syntax reaches the same optimized plan.
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

    # TODO: Register emp_df as a temp view called "employees"
    # Your code here

    # TODO: DataFrame API: filter salary > 50000, group by department,
    #       avg(salary) AS avg_salary, order by avg_salary desc
    df_result = None  # Replace

    # TODO: Same query in standard SQL with spark.sql()
    sql_result = None  # Replace

    # TODO: Same query in SQL pipe syntax:
    #       FROM employees |> WHERE ... |> AGGREGATE ... GROUP BY ... |> ORDER BY ...
    pipe_result = None  # Replace

    # TODO: Capture both plans with the plan_text() helper above
    df_plan = None  # Replace
    sql_plan = None  # Replace

    # TODO: Top earner per department using QUALIFY with ROW_NUMBER()
    #       Columns: department, name, salary
    top_earners = None  # Replace

    return {
        "df_result": df_result,
        "sql_result": sql_result,
        "pipe_result": pipe_result,
        "df_plan": df_plan,
        "sql_plan": sql_plan,
        "top_earners": top_earners,
    }


# ---- Test harness (do not modify below this line) ----
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
