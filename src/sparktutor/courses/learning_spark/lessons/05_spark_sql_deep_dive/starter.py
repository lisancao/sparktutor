"""
Spark SQL Deep Dive - Starter Code

Implement the `compare_plans` function that:
1. Creates a sample employee DataFrame
2. Writes a query using the DataFrame API: filter salary > 50000,
   group by department, compute average salary, order by avg desc
3. Writes the same query using Spark SQL
4. Returns a dict with keys "df_plan" and "sql_plan" containing
   the string explain output for each approach

This demonstrates that both APIs produce equivalent execution plans.
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
    """Compare DataFrame API and SQL execution plans."""

    emp_df = spark.createDataFrame(EMPLOYEE_DATA, SCHEMA)

    # TODO: Register as a temp view for SQL queries
    # Your code here

    # TODO: DataFrame API approach — filter salary > 50000,
    #       group by department, avg salary, order by avg desc
    df_result = None  # Replace

    # TODO: SQL approach — same logic as above using spark.sql()
    sql_result = None  # Replace

    # Capture explain plans as strings
    # (explain() prints to stdout; we capture it)
    df_plan = df_result._jdf.queryExecution().simpleString()
    sql_plan = sql_result._jdf.queryExecution().simpleString()

    return {
        "df_result": df_result,
        "sql_result": sql_result,
        "df_plan": df_plan,
        "sql_plan": sql_plan,
    }


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("SQLDeepDiveTest")
        .master("local[*]")
        .getOrCreate())

    result = compare_plans(spark)
    assert result is not None, "Function returned None"
    assert result["df_result"].count() == 3, "DataFrame API should return 3 departments"
    assert result["sql_result"].count() == 3, "SQL should return 3 departments"
    assert len(result["df_plan"]) > 0, "df_plan should not be empty"
    assert len(result["sql_plan"]) > 0, "sql_plan should not be empty"
    print("DataFrame API result:")
    result["df_result"].show()
    print("SQL result:")
    result["sql_result"].show()
    print("All tests passed!")
    spark.stop()
