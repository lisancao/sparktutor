"""
Bronze 层 - 起始代码

实现 `bronze_orders` 函数：
1. 使用全 StringType schema 从 `csv_path` 读取 CSV
2. 添加 `_ingested_at` 列（当前时间戳）
3. 添加 `_source_file` 列（输入文件名）
4. 按 `order_id` 去重

返回的 DataFrame 的预期 schema：
  order_id: string
  product: string
  price: string       （保留为 string，采用 schema-on-read 模式）
  quantity: string     （保留为 string，采用 schema-on-read 模式）
  _ingested_at: timestamp
  _source_file: string
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType


def bronze_orders(spark, csv_path):
    """将原始订单 CSV 摄取到 bronze DataFrame。"""

    # TODO: 定义全 StringType schema，包含以下列：
    #       order_id, product, price, quantity
    schema = None  # 替换为 StructType(...)

    # TODO: 使用上述 schema 读取 CSV（header=True）
    raw = None  # 替换为 spark.read...

    # TODO: 添加 _ingested_at 和 _source_file 列
    with_meta = None  # 替换

    # TODO: 按 order_id 去重
    deduped = None  # 替换

    return deduped


# ---- 测试代码（请勿修改此行以下内容）----
if __name__ == "__main__":
    import tempfile, os

    spark = SparkSession.builder.appName("BronzeTest").master("local[*]").getOrCreate()

    # 创建测试 CSV 文件
    tmp = tempfile.mkdtemp()
    csv_path = os.path.join(tmp, "orders.csv")
    with open(csv_path, "w") as fh:
        fh.write("order_id,product,price,quantity\n")
        fh.write("1,widget,9.99,2\n")
        fh.write("2,gadget,24.99,1\n")
        fh.write("1,widget,9.99,2\n")  # 重复行

    df = bronze_orders(spark, csv_path)
    assert df.count() == 2, f"去重后预期 2 行，实际得到 {df.count()}"
    assert "_ingested_at" in df.columns, "缺少 _ingested_at 列"
    assert "_source_file" in df.columns, "缺少 _source_file 列"
    assert df.schema["price"].dataType == StringType(), "price 应为 StringType"
    print("所有测试通过！")
    spark.stop()
