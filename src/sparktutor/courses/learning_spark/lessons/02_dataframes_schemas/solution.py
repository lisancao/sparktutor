"""
DataFrame 与 Schema - 参考答案

完整的 DataFrame 创建：显式 schema、复杂类型、计算列。
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, ArrayType
)


DATA = [
    [1, "Jules", "Damji", "https://tinyurl.1", "1/4/2016", 4535, ["twitter", "LinkedIn"]],
    [2, "Brooke", "Wenig", "https://tinyurl.2", "5/5/2018", 8908, ["twitter", "LinkedIn"]],
    [3, "Denny", "Lee", "https://tinyurl.3", "6/7/2019", 7659, ["web", "twitter", "FB", "LinkedIn"]],
    [4, "Tathagata", "Das", "https://tinyurl.4", "5/12/2018", 10568, ["twitter", "FB"]],
    [5, "Matei", "Zaharia", "https://tinyurl.5", "5/14/2014", 40578, ["web", "twitter", "FB", "LinkedIn"]],
    [6, "Reynold", "Xin", "https://tinyurl.6", "3/2/2015", 25568, ["twitter", "LinkedIn"]],
]


def build_blogs_df(spark):
    """创建包含 schema、数据和计算列的博客 DataFrame。"""

    schema = StructType([
        StructField("Id", IntegerType(), False),
        StructField("First", StringType(), False),
        StructField("Last", StringType(), False),
        StructField("Url", StringType(), False),
        StructField("Published", StringType(), False),
        StructField("Hits", IntegerType(), False),
        StructField("Campaigns", ArrayType(StringType()), False),
    ])

    blogs_df = spark.createDataFrame(DATA, schema)

    result = blogs_df.withColumn("Big_Hitter", f.col("Hits") > 10000)

    return result


# ---- 测试代码 ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("BlogsTest")
        .master("local[*]")
        .getOrCreate())

    df = build_blogs_df(spark)
    assert df is not None, "函数返回了 None"
    assert df.count() == 6, f"预期 6 行，实际得到 {df.count()}"
    assert "Big_Hitter" in df.columns, "缺少 Big_Hitter 列"
    assert "Campaigns" in df.columns, "缺少 Campaigns 列"

    big_hitters = df.filter(f.col("Big_Hitter") == True).count()
    assert big_hitters == 3, f"预期 3 个高访问量博客，实际得到 {big_hitters}"
    print("所有测试通过！")
    df.show(truncate=False)
    spark.stop()
