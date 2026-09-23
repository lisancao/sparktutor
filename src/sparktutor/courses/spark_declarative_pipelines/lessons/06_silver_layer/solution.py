"""
Silver 层 - 参考答案

清洗、类型转换和丰富 bronze 数据为 silver 层。
"""

from pyspark.sql import SparkSession, functions as f


def silver_orders(spark):
    """将 bronze_orders 转换为干净的 silver DataFrame。"""

    bronze = spark.table("bronze_orders")

    # 将字符串列转为正确的类型
    typed = (bronze
        .withColumn("price", f.col("price").cast("double"))
        .withColumn("quantity", f.col("quantity").cast("int"))
    )

    # 计算总额
    with_total = typed.withColumn("total", f.col("price") * f.col("quantity"))

    # 过滤掉无法解析 price 的行
    clean = with_total.filter(f.col("price").isNotNull())

    # 从订单时间戳字符串中提取小时
    enriched = clean.withColumn("order_hour", f.hour(f.to_timestamp(f.col("order_ts"))))

    return enriched


# ---- 测试代码 ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("SilverTest").master("local[*]").getOrCreate()

    data = [
        ("1", "widget", "9.99", "2", "2026-01-15 14:30:00"),
        ("2", "gadget", "24.99", "1", "2026-01-15 09:15:00"),
        ("3", "doohickey", "N/A", "3", "2026-01-15 22:00:00"),
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
