"""
内置数据源 - 起始代码

实现 `data_pipeline` 函数：
1. 创建一个航班数据示例 DataFrame
2. 将其以 Parquet 格式写入指定路径
3. 重新读取 Parquet 为新的 DataFrame
4. 创建名为 "flights" 的临时 SQL 视图
5. 运行 SQL 查询，找出按总延误时间排名前 3 的目的地
6. 返回查询结果 DataFrame

本练习涵盖 DataFrameReader、DataFrameWriter、临时视图和 SQL。
"""

from pyspark.sql import SparkSession, functions as f, Row
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType
)


FLIGHT_DATA = [
    ("SFO", "JFK", 45), ("SFO", "JFK", 60), ("SFO", "LAX", 10),
    ("SFO", "LAX", 15), ("SFO", "ORD", 90), ("SFO", "ORD", 30),
    ("SFO", "SEA", 5),  ("SFO", "SEA", 20), ("SFO", "DEN", 35),
]

SCHEMA = StructType([
    StructField("origin", StringType(), False),
    StructField("destination", StringType(), False),
    StructField("delay", IntegerType(), False),
])


def data_pipeline(spark, output_path):
    """读取、写入并查询航班数据。"""

    # TODO: 使用 SCHEMA 从 FLIGHT_DATA 创建 DataFrame
    flights_df = None  # 替换

    # TODO: 将 DataFrame 以 Parquet 格式写入 output_path（overwrite 模式）
    # 在此编写代码

    # TODO: 重新读取 Parquet 为新的 DataFrame
    parquet_df = None  # 替换

    # TODO: 创建名为 "flights" 的临时视图
    # 在此编写代码

    # TODO: 运行 SQL 查询，找出按总延误时间排名前 3 的目的地
    #       SELECT destination, SUM(delay) AS total_delay
    #       FROM flights GROUP BY destination
    #       ORDER BY total_delay DESC LIMIT 3
    result = None  # 替换为 spark.sql(...)

    return result


# ---- 测试代码（请勿修改此行以下内容）----
if __name__ == "__main__":
    import tempfile, os, shutil

    spark = (SparkSession.builder
        .appName("DataSourcesTest")
        .master("local[*]")
        .getOrCreate())

    tmp = tempfile.mkdtemp()
    out_path = os.path.join(tmp, "flights_parquet")

    try:
        df = data_pipeline(spark, out_path)
        assert df is not None, "函数返回了 None"
        assert df.count() == 3, f"预期 3 行，实际得到 {df.count()}"
        cols = [c.lower() for c in df.columns]
        assert "destination" in cols, f"缺少 destination 列，实际得到 {cols}"
        assert "total_delay" in cols, f"缺少 total_delay 列，实际得到 {cols}"
        top = df.collect()[0]
        assert top.destination == "ORD", f"预期 ORD 为排名第一的目的地，实际得到 {top.destination}"
        print("所有测试通过！")
        df.show(truncate=False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        spark.stop()
