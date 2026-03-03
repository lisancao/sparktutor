"""
Machine Learning with MLlib - Solution

Complete ML pipeline for housing price prediction.
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
    """Generate synthetic housing data for ML training."""
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
    """Build and evaluate an ML pipeline for housing price prediction."""

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


# ---- Test harness ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("MLlibTest")
        .master("local[*]")
        .getOrCreate())

    result = build_pipeline(spark)
    assert result is not None, "Function returned None"
    assert result["model"] is not None, "Model is None"
    assert result["predictions"] is not None, "Predictions is None"
    assert result["rmse"] is not None, "RMSE is None"
    assert result["r2"] is not None, "R2 is None"
    assert result["rmse"] > 0, f"RMSE should be positive, got {result['rmse']}"
    assert 0 < result["r2"] <= 1, f"R2 should be between 0 and 1, got {result['r2']}"
    print(f"Training samples: {result['train_count']}")
    print(f"Test samples: {result['test_count']}")
    print(f"RMSE: {result['rmse']:.2f}")
    print(f"R2: {result['r2']:.4f}")
    print("\nSample predictions:")
    result["predictions"].select("neighborhood", "condition", "bedrooms",
                                  "sqft", "age", "price", "prediction").show(10)
    print("All tests passed!")
    spark.stop()
