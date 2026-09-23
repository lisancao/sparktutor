"""
Silver 层 - 起始代码

实现 `silver_orders` 函数：
1. 从 'bronze_orders' 临时视图读取
2. 将 `price` 转为 double，`quantity` 转为 int
3. 添加 `total` 列（price * quantity）
4. 过滤掉 price 为 null 的行（脏数据）
5. 添加 `order_hour` 列：从 `order_ts` 中提取小时

预期输出列：
  order_id, product, price (double), quantity (int), order_ts (string),
  _ingested_at, total (double), order_hour (int)
"""

from pyspark.sql import SparkSession, functions as f


def silver_orders(spark):
    """将 bronze_orders 转换为干净的 silver DataFrame。"""

    bronze = spark.table("bronze_orders")

    # TODO: 将 price 转为 double，quantity 转为 int
    typed = bronze  # 替换

    # TODO: 添加 'total' 列 = price * quantity
    with_total = typed  # 替换

    # TODO: 过滤掉 price 为 null 的行
    clean = with_total  # 替换

    # TODO: 添加 'order_hour' = 从 order_ts 中提取小时
    #       （order_ts 是类似 '2026-01-15 14:30:00' 的字符串）
    enriched = clean  # 替换

    return enriched


# ---- 测试代码（请勿修改此行以下内容）----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("SilverTest").master("local[*]").getOrCreate()

    # 创建 bronze 测试数据
    data = [
        ("1", "widget", "9.99", "2", "2026-01-15 14:30:00"),
        ("2", "gadget", "24.99", "1", "2026-01-15 09:15:00"),
        ("3", "doohickey", "N/A", "3", "2026-01-15 22:00:00"),  # 坏价格
    ]
    bronze = spark.createDataFrame(data, ["order_id", "product", "price", "quantity", "order_ts"])
    bronze = bronze.withColumn("_ingested_at", f.current_timestamp())
    bronze.createOrReplaceTempView("bronze_orders")

    df = silver_orders(spark)
    assert df.count() == 2, f"预期 2 行（过滤掉 1 行），实际得到 {df.count()}"
    assert "total" in df.columns, "缺少 'total' 列"
    assert "order_hour" in df.columns, "缺少 'order_hour' 列"

    row = df.filter(f.col("order_id") == "1").first()
    assert abs(row["total"] - 19.98) < 0.01, f"预期 total 约 19.98，实际得到 {row['total']}"
    assert row["order_hour"] == 14, f"预期 order_hour 为 14，实际得到 {row['order_hour']}"

    print("所有测试通过！")
    df.show(truncate=False)
    spark.stop()
