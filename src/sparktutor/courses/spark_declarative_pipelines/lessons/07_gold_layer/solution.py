"""
Gold 层 - 参考答案

产品级聚合与营收排名。
"""

from pyspark.sql import SparkSession, functions as f, Window


def gold_product_summary(spark):
    """生成带有排名的 gold 层产品汇总。"""

    silver = spark.table("silver_orders")

    # 按产品聚合
    agg_df = (silver
        .groupBy("product")
        .agg(
            f.count("*").alias("order_count"),
            f.sum("total").alias("total_revenue"),
            f.avg("total").alias("avg_order_value"),
        )
    )

    # 按营收排名（最高在前）
    w = Window.orderBy(f.col("total_revenue").desc())
    ranked = agg_df.withColumn("revenue_rank", f.rank().over(w))

    return ranked


# ---- 测试代码 ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("GoldTest").master("local[*]").getOrCreate()

    data = [
        ("1", "widget", 9.99, 2, 19.98, 14),
        ("2", "gadget", 24.99, 1, 24.99, 9),
        ("3", "widget", 9.99, 5, 49.95, 16),
        ("4", "gizmo", 4.99, 10, 49.90, 11),
    ]
    silver = spark.createDataFrame(
        data, ["order_id", "product", "price", "quantity", "total", "order_hour"]
    )
    silver.createOrReplaceTempView("silver_orders")

    df = gold_product_summary(spark)

    assert df.count() == 3, f"预期 3 个产品，实际得到 {df.count()}"
    assert "revenue_rank" in df.columns, "缺少 'revenue_rank' 列"
    assert "total_revenue" in df.columns, "缺少 'total_revenue' 列"

    top = df.filter(f.col("revenue_rank") == 1).first()
    assert top["product"] == "widget", f"预期 widget 排名第一，实际得到 {top['product']}"

    print("所有测试通过！")
    df.show(truncate=False)
    spark.stop()
