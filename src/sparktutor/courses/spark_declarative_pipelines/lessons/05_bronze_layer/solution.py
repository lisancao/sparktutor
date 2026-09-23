"""
Bronze 层 - 参考答案

完整的 bronze 摄取：schema-on-read、元数据列和去重。
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType


def bronze_orders(spark, csv_path):
    """将原始订单 CSV 摄取到 bronze DataFrame。"""

    schema = StructType([
        StructField("order_id", StringType()),
        StructField("product", StringType()),
        StructField("price", StringType()),
        StructField("quantity", StringType()),
    ])

    raw = spark.read.csv(csv_path, header=True, schema=schema)

    with_meta = (raw
        .withColumn("_ingested_at", f.current_timestamp())
        .withColumn("_source_file", f.input_file_name())
    )

    deduped = with_meta.dropDuplicates(["order_id"])

    return deduped


# ---- 测试代码 ----
if __name__ == "__main__":
    import tempfile, os

    spark = SparkSession.builder.appName("BronzeTest").master("local[*]").getOrCreate()

    tmp = tempfile.mkdtemp()
    csv_path = os.path.join(tmp, "orders.csv")
    with open(csv_path, "w") as fh:
        fh.write("order_id,product,price,quantity\n")
        fh.write("1,widget,9.99,2\n")
        fh.write("2,gadget,24.99,1\n")
        fh.write("1,widget,9.99,2\n")

    df = bronze_orders(spark, csv_path)
    assert df.count() == 2, f"去重后预期 2 行，实际得到 {df.count()}"
    assert "_ingested_at" in df.columns, "缺少 _ingested_at 列"
    assert "_source_file" in df.columns, "缺少 _source_file 列"
    assert df.schema["price"].dataType == StringType(), "price 应为 StringType"
    print("所有测试通过！")
    df.show(truncate=False)
    spark.stop()
