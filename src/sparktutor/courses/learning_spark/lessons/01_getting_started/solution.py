"""
M&M 糖果数量分析 - 参考答案

完整分析流程：读取 CSV，按 State+Color 聚合，
筛选加利福尼亚州。
"""

from pyspark.sql import SparkSession, functions as f


def mnm_analysis(spark, file_path):
    """从 CSV 数据中分析 M&M 糖果数量。"""

    mnm_df = (spark.read.format("csv")
        .option("header", "true")
        .option("inferSchema", "true")
        .load(file_path))

    count_mnm_df = (mnm_df
        .groupBy("State", "Color")
        .agg(f.sum("Count").alias("Total"))
        .orderBy(f.col("Total").desc()))

    ca_count_mnm_df = count_mnm_df.filter(f.col("State") == "CA")

    return ca_count_mnm_df


# ---- 测试代码 ----
if __name__ == "__main__":
    import tempfile, os

    spark = (SparkSession.builder
        .appName("MnMTest")
        .master("local[*]")
        .getOrCreate())

    tmp = tempfile.mkdtemp()
    csv_path = os.path.join(tmp, "mnm_dataset.csv")
    with open(csv_path, "w") as fh:
        fh.write("State,Color,Count\n")
        fh.write("CA,Yellow,1230\n")
        fh.write("CA,Brown,1500\n")
        fh.write("TX,Green,1200\n")
        fh.write("TX,Red,1100\n")
        fh.write("CA,Yellow,800\n")
        fh.write("NY,Blue,900\n")

    df = mnm_analysis(spark, csv_path)
    assert df is not None, "函数返回了 None"
    states = [row.State for row in df.collect()]
    assert all(s == "CA" for s in states), f"预期仅包含 CA 行，实际得到 {states}"
    assert df.count() == 2, f"预期 2 个 CA 颜色分组，实际得到 {df.count()}"
    print("所有测试通过！")
    df.show(truncate=False)
    spark.stop()
