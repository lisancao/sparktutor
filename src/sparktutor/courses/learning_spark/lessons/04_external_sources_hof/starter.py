"""
外部数据源与高阶函数 - 起始代码

实现 `analyze_orders` 函数：
1. 创建包含数组列 "items" 的订单 DataFrame
2. 使用 transform() 将每个订单中的所有商品转为大写
3. 使用 filter() 仅保留以 "p" 开头的商品
4. 在每个区域内按总额（降序）添加排名
5. 返回结果 DataFrame

本练习涵盖高阶函数和窗口函数。
"""

from pyspark.sql import SparkSession, functions as f, Window
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, ArrayType, DoubleType
)


ORDER_DATA = [
    (1, "West", 150.0, ["pen", "paper", "pencil"]),
    (2, "West", 280.0, ["printer", "paper", "ink"]),
    (3, "East", 95.0,  ["pencil", "eraser"]),
    (4, "East", 320.0, ["projector", "screen", "cable"]),
    (5, "West", 210.0, ["phone", "case", "charger"]),
    (6, "East", 175.0, ["paper", "pen", "folder"]),
]

SCHEMA = StructType([
    StructField("order_id", IntegerType(), False),
    StructField("region", StringType(), False),
    StructField("total", DoubleType(), False),
    StructField("items", ArrayType(StringType()), False),
])


def analyze_orders(spark):
    """使用高阶函数和窗口函数分析订单。"""

    orders_df = spark.createDataFrame(ORDER_DATA, SCHEMA)

    # TODO: 使用 transform() 将 "items" 数组中的所有商品转为大写
    #       作为新列 "items_upper" 添加
    with_upper = None  # 替换

    # TODO: 对 "items" 使用 filter() 仅保留以 "p" 开头的商品
    #       作为新列 "p_items" 添加
    with_p_items = None  # 替换

    # TODO: 添加排名列 "region_rank"，使用窗口函数在每个区域内
    #       按总额（降序）对订单排名
    w = None  # 定义窗口规范
    result = None  # 添加排名列

    return result


# ---- 测试代码（请勿修改此行以下内容）----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("HOFTest")
        .master("local[*]")
        .getOrCreate())

    df = analyze_orders(spark)
    assert df is not None, "函数返回了 None"
    assert "items_upper" in df.columns, "缺少 items_upper 列"
    assert "p_items" in df.columns, "缺少 p_items 列"
    assert "region_rank" in df.columns, "缺少 region_rank 列"
    assert df.count() == 6, f"预期 6 行，实际得到 {df.count()}"

    # 验证大写转换是否生效
    first_upper = df.filter(f.col("order_id") == 1).select("items_upper").collect()[0][0]
    assert first_upper == ["PEN", "PAPER", "PENCIL"], f"items_upper 错误：{first_upper}"

    print("所有测试通过！")
    df.show(truncate=False)
    spark.stop()
