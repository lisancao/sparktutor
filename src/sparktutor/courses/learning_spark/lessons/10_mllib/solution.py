"""
使用 MLlib 进行机器学习 - 参考答案

完整的房价预测 ML Pipeline。
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

    (trainDF, testDF) = housing_df.randomSplit([0.8, 0.2], seed=42)

    neighborhood_indexer = StringIndexer(
        inputCol="neighborhood", outputCol="neighborhoodIndex", handleInvalid="skip"
    )
    condition_indexer = StringIndexer(
        inputCol="condition", outputCol="conditionIndex", handleInvalid="skip"
    )

    assembler = VectorAssembler(
        inputCols=["neighborhoodIndex", "conditionIndex", "bedrooms", "sqft", "age"],
        outputCol="features"
    )

    rf = RandomForestRegressor(
        labelCol="price", featuresCol="features",
        numTrees=20, maxDepth=5, seed=42
    )

    pipeline = Pipeline(stages=[neighborhood_indexer, condition_indexer, assembler, rf])

    model = pipeline.fit(trainDF)

    predictions = model.transform(testDF)

    evaluator = RegressionEvaluator(labelCol="price", predictionCol="prediction")
    rmse = evaluator.setMetricName("rmse").evaluate(predictions)
    r2 = evaluator.setMetricName("r2").evaluate(predictions)

    return {
        "model": model,
        "predictions": predictions,
        "rmse": rmse,
        "r2": r2,
        "train_count": trainDF.count(),
        "test_count": testDF.count(),
    }


# ---- 测试代码 ----
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
