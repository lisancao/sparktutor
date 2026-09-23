"""
数据湖与湖仓一体 - 参考答案

使用 Parquet 目录模拟湖仓版本管理。
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType
)
import os


INITIAL_DATA = [
    (1, "Alice", "Engineering", 85000.0),
    (2, "Bob", "Marketing", 65000.0),
    (3, "Charlie", "Sales", 55000.0),
]

NEW_EMPLOYEES = [
    (4, "Diana", "Engineering", 92000.0),
    (5, "Eve", "Marketing", 70000.0),
]

SCHEMA = StructType([
    StructField("id", IntegerType(), False),
    StructField("name", StringType(), False),
    StructField("department", StringType(), False),
    StructField("salary", DoubleType(), False),
])


def lakehouse_simulation(spark, base_path):
    """使用 Parquet 目录模拟湖仓版本管理。"""

    v0_path = os.path.join(base_path, "v0")
    v1_path = os.path.join(base_path, "v1")

    initial_df = spark.createDataFrame(INITIAL_DATA, SCHEMA)
    initial_df.write.parquet(v0_path)

    new_df = spark.createDataFrame(NEW_EMPLOYEES, SCHEMA)
    combined_df = initial_df.union(new_df)
    combined_df.write.parquet(v1_path)

    version_0 = spark.read.parquet(v0_path)
    version_1 = spark.read.parquet(v1_path)

    schemas_match = version_0.schema == version_1.schema

    return {
        "version_0": version_0,
        "version_1": version_1,
        "v0_count": version_0.count(),
        "v1_count": version_1.count(),
        "schemas_match": schemas_match,
    }


# ---- 测试代码 ----
if __name__ == "__main__":
    import tempfile, shutil

    spark = (SparkSession.builder
        .appName("LakehouseTest")
        .master("local[*]")
        .getOrCreate())

    tmp = tempfile.mkdtemp()
    base = os.path.join(tmp, "lakehouse")

    try:
        result = lakehouse_simulation(spark, base)
        assert result is not None, "函数返回了 None"
        assert result["v0_count"] == 3, f"版本 0 应有 3 行，实际得到 {result['v0_count']}"
        assert result["v1_count"] == 5, f"版本 1 应有 5 行，实际得到 {result['v1_count']}"
        assert result["schemas_match"] == True, "各版本之间的 schema 应一致"
        print("版本 0（初始）：")
        result["version_0"].show()
        print("版本 1（含新员工）：")
        result["version_1"].show()
        print(f"Schema 是否一致：{result['schemas_match']}")
        print("所有测试通过！")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        spark.stop()
