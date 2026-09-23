"""
M&M 糖果数量分析 - 起始代码

实现 `mnm_analysis` 函数：
1. 读取包含以下列的 CSV 文件：State, Color, Count
2. 按 State 和 Color 分组，对 Count 列求和
3. 按求和结果降序排列
4. 仅筛选加利福尼亚州（'CA'）的数据
5. 返回仅包含加利福尼亚州的 DataFrame

本练习基于 Learning Spark 中的 M&M 糖果计数示例。
"""

from pyspark.sql import SparkSession, functions as f


def mnm_analysis(spark, file_path):
    """从 CSV 数据中分析 M&M 糖果数量。"""

    # TODO: 使用 header 和 inferSchema 选项读取 CSV 文件
    mnm_df = None  # 替换为 spark.read...

    # TODO: 按 State 和 Color 分组，对 Count 列求和，
    #       并按求和结果降序排列
    count_mnm_df = None  # 替换

    # TODO: 仅筛选加利福尼亚州（'CA'）的数据
    ca_count_mnm_df = None  # 替换

    return ca_count_mnm_df


# ---- 测试代码（请勿修改此行以下内容）----
if __name__ == "__main__":
    import tempfile, os

    spark = (SparkSession.builder
        .appName("MnMTest")
        .master("local[*]")
        .getOrCreate())

    # 创建测试 CSV 文件
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
