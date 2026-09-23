"""
数据湖与湖仓一体 - 起始代码

实现 `lakehouse_simulation` 函数，使用 Parquet + 版本化目录
模拟湖仓概念：
1. 创建初始员工数据并写为 "版本 0"
2. 添加新员工并写为 "版本 1"
3. 读取两个版本以演示 "时间旅行"
4. 验证版本之间的 schema 一致性
5. 返回包含两个版本和 schema 信息的字典

兼容 dry-run — 无需 Delta/Iceberg JAR。
在生产环境中，你可以使用 Delta 或 Iceberg 获得真正的 ACID 支持。
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

    # TODO: 创建初始 DataFrame 并以 Parquet 格式写入 v0_path
    initial_df = None  # 替换
    # 在此写入 v0_path

    # TODO: 创建新员工 DataFrame，与初始数据 union，
    #       并以 Parquet 格式写入 v1_path
    new_df = None  # 替换
    combined_df = None  # 替换（initial_df 和 new_df 的 union）
    # 在此写入 v1_path

    # TODO: 读取两个版本（模拟时间旅行）
    version_0 = None  # 替换 — 从 v0_path 读取
    version_1 = None  # 替换 — 从 v1_path 读取

    # TODO: 验证 schema 一致性
    schemas_match = None  # 替换 — 比较 version_0.schema == version_1.schema

    return {
        "version_0": version_0,
        "version_1": version_1,
        "v0_count": version_0.count(),
        "v1_count": version_1.count(),
        "schemas_match": schemas_match,
    }


# ---- 测试代码（请勿修改此行以下内容）----
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
