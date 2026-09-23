"""
DataFrame 与 Schema - 起始代码

实现 `build_blogs_df` 函数：
1. 定义包含以下字段的 schema：Id (int), First (string), Last (string),
   Url (string), Published (string), Hits (int), Campaigns (字符串数组)
2. 使用该 schema 从提供的数据创建 DataFrame
3. 添加布尔列 "Big_Hitter"，当 Hits > 10000 时为 True
4. 返回 DataFrame

本练习基于 Learning Spark 中的 Example-3_6。
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, ArrayType
)


# 博客作者示例数据
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

    # TODO: 使用 StructType 定义上述列的 schema
    #       注意：Campaigns 应为 ArrayType(StringType())
    schema = None  # 替换为 StructType(...)

    # TODO: 使用 schema 从 DATA 创建 DataFrame
    blogs_df = None  # 替换为 spark.createDataFrame(...)

    # TODO: 添加布尔列 "Big_Hitter"，当 Hits > 10000 时为 True
    result = None  # 替换

    return result


# ---- 测试代码（请勿修改此行以下内容）----
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
