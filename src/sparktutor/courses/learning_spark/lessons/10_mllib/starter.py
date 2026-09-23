"""
使用 MLlib 进行机器学习 - 起始代码

实现 `build_pipeline` 函数：
1. 创建包含类别特征和数值特征的房屋示例数据集
2. 拆分为训练集/测试集（80/20）
3. 构建包含 StringIndexer、VectorAssembler、RandomForestRegressor 的 Pipeline
4. 在训练数据上拟合 Pipeline
5. 在测试预测上评估 RMSE 和 R2
6. 返回包含模型、预测和指标的字典

改编自 Learning Spark 的 MLflow train.py 示例。
"""

from pyspark.sql import SparkSession
from pyspark.ml import Pipeline
from pyspark.ml.feature import StringIndexer, VectorAssembler
from pyspark.ml.regression import RandomForestRegressor
from pyspark.ml.evaluation import RegressionEvaluator
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType
)
import random


def generate_housing_data(n=500):
    """生成用于 ML 训练的合成房屋数据。"""
    neighborhoods = ["Downtown", "Suburbs", "Rural", "Midtown", "Waterfront"]
    conditions = ["Excellent", "Good", "Fair", "Poor"]
    random.seed(42)
    data = []
    for i in range(n):
        neighborhood = random.choice(neighborhoods)
        condition = random.choice(conditions)
        bedrooms = random.randint(1, 5)
        sqft = random.randint(500, 4000)
        age = random.randint(0, 80)

        # 基于特征计算价格（含一些噪声）
        base = {"Downtown": 300000, "Suburbs": 200000, "Rural": 100000,
                "Midtown": 250000, "Waterfront": 400000}
        cond = {"Excellent": 1.3, "Good": 1.1, "Fair": 0.9, "Poor": 0.7}
        price = (base[neighborhood] * cond[condition]
                 + bedrooms * 25000 + sqft * 100 - age * 1000
                 + random.gauss(0, 20000))
        data.append((neighborhood, condition, bedrooms, sqft, age, round(price, 2)))
    return data


SCHEMA = StructType([
    StructField("neighborhood", StringType(), False),
    StructField("condition", StringType(), False),
    StructField("bedrooms", IntegerType(), False),
    StructField("sqft", IntegerType(), False),
    StructField("age", IntegerType(), False),
    StructField("price", DoubleType(), False),
])


def build_pipeline(spark):
    """构建并评估用于房价预测的 ML Pipeline。"""

    housing_df = spark.createDataFrame(generate_housing_data(), SCHEMA)

    # TODO: 拆分为训练集（80%）和测试集（20%），seed=42
    trainDF, testDF = None, None  # 替换

    # TODO: 为类别列创建 StringIndexer
    #       "neighborhood" -> "neighborhoodIndex"
    #       "condition" -> "conditionIndex"
    neighborhood_indexer = None  # 替换
    condition_indexer = None  # 替换

    # TODO: 创建 VectorAssembler，合并以下列：
    #       ["neighborhoodIndex", "conditionIndex", "bedrooms", "sqft", "age"]
    #       到名为 "features" 的列中
    assembler = None  # 替换

    # TODO: 创建 RandomForestRegressor，labelCol="price"，
    #       numTrees=20, maxDepth=5, seed=42
    rf = None  # 替换

    # TODO: 创建 Pipeline，stages 为：
    #       [neighborhood_indexer, condition_indexer, assembler, rf]
    pipeline = None  # 替换

    # TODO: 在 trainDF 上拟合 Pipeline
    model = None  # 替换

    # TODO: 对 testDF 进行变换以获取预测
    predictions = None  # 替换

    # TODO: 评估 RMSE 和 R2
    evaluator = RegressionEvaluator(labelCol="price", predictionCol="prediction")
    rmse = None  # 替换 — 使用 setMetricName("rmse").evaluate()
    r2 = None  # 替换 — 使用 setMetricName("r2").evaluate()

    return {
        "model": model,
        "predictions": predictions,
        "rmse": rmse,
        "r2": r2,
        "train_count": trainDF.count(),
        "test_count": testDF.count(),
    }


# ---- 测试代码（请勿修改此行以下内容）----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("MLlibTest")
        .master("local[*]")
        .getOrCreate())

    result = build_pipeline(spark)
    assert result is not None, "函数返回了 None"
    assert result["model"] is not None, "模型为 None"
    assert result["predictions"] is not None, "预测为 None"
    assert result["rmse"] is not None, "RMSE 为 None"
    assert result["r2"] is not None, "R2 为 None"
    assert result["rmse"] > 0, f"RMSE 应为正数，实际得到 {result['rmse']}"
    assert 0 < result["r2"] <= 1, f"R2 应在 0 到 1 之间，实际得到 {result['r2']}"
    print(f"训练样本数：{result['train_count']}")
    print(f"测试样本数：{result['test_count']}")
    print(f"RMSE：{result['rmse']:.2f}")
    print(f"R2：{result['r2']:.4f}")
    print("\n预测示例：")
    result["predictions"].select("neighborhood", "condition", "bedrooms",
                                  "sqft", "age", "price", "prediction").show(10)
    print("所有测试通过！")
    spark.stop()
