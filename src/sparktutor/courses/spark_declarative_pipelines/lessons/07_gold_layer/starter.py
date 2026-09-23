"""
Gold 层 - 起始代码

实现 `gold_product_summary` 函数：
1. 从 'silver_orders' 临时视图读取
2. 按 `product` 分组
3. 计算：order_count, total_revenue, avg_order_value
4. 添加 `revenue_rank` 列（按 total_revenue 降序排名）

预期输出列：
  product, order_count, total_revenue, avg_order_value, revenue_rank
"""

from pyspark.sql import SparkSession, functions as f, Window


def gold_product_summary(spark):
    """生成带有排名的 gold 层产品汇总。"""

    silver = spark.table("silver_orders")

    # TODO: 按 product 分组并计算聚合
    agg_df = silver  # 替换

    # TODO: 使用窗口函数添加 revenue_rank
    #       排名第 1 = total_revenue 最高
    ranked = agg_df  # 替换

    return ranked


# ---- 测试代码（请勿修改此行以下内容）----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("GoldTest").master("local[*]").getOrCreate()

    # 创建 silver 测试数据
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
