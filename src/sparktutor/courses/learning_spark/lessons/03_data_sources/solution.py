"""
内置数据源 - 参考答案

完整数据管道：创建、写入 Parquet、重新读取、
创建 SQL 视图并查询。
"""

from pyspark.sql import SparkSession, functions as f
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

    flights_df = spark.createDataFrame(FLIGHT_DATA, SCHEMA)

    flights_df.write.mode("overwrite").parquet(output_path)

    parquet_df = spark.read.parquet(output_path)

    parquet_df.createOrReplaceTempView("flights")

    result = spark.sql("""
        SELECT destination, SUM(delay) AS total_delay
        FROM flights
        GROUP BY destination
        ORDER BY total_delay DESC
        LIMIT 3
    """)

    return result


# ---- 测试代码 ----
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
