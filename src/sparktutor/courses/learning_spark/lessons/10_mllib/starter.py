"""
Machine Learning with MLlib - Starter Code

Implement the `build_pipeline` function that:
1. Creates a sample housing dataset with categorical and numeric features
2. Splits into train/test sets (80/20)
3. Builds a Pipeline with StringIndexer, VectorAssembler, RandomForestRegressor
4. Trains the pipeline on training data
5. Evaluates RMSE and R2 on test predictions
6. Returns a dict with the model, predictions, and metrics

Adapted from the Learning Spark MLflow train.py example.
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

        # Price based on features (with some noise)
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

    # TODO: Split into train (80%) and test (20%) with seed=42
    trainDF, testDF = None, None  # Replace

    # TODO: Create StringIndexers for categorical columns
    #       "neighborhood" -> "neighborhoodIndex"
    #       "condition" -> "conditionIndex"
    neighborhood_indexer = None  # Replace
    condition_indexer = None  # Replace

    # TODO: Create VectorAssembler combining:
    #       ["neighborhoodIndex", "conditionIndex", "bedrooms", "sqft", "age"]
    #       into a column called "features"
    assembler = None  # Replace

    # TODO: Create RandomForestRegressor with labelCol="price",
    #       numTrees=20, maxDepth=5, seed=42
    rf = None  # Replace

    # TODO: Create a Pipeline with stages:
    #       [neighborhood_indexer, condition_indexer, assembler, rf]
    pipeline = None  # Replace

    # TODO: Fit the pipeline on trainDF
    model = None  # Replace

    # TODO: Transform testDF to get predictions
    predictions = None  # Replace

    # TODO: Evaluate RMSE and R2
    evaluator = RegressionEvaluator(labelCol="price", predictionCol="prediction")
    rmse = None  # Replace — use setMetricName("rmse").evaluate()
    r2 = None  # Replace — use setMetricName("r2").evaluate()

    return {
        "model": model,
        "predictions": predictions,
        "rmse": rmse,
        "r2": r2,
        "train_count": trainDF.count(),
        "test_count": testDF.count(),
    }


# ---- Test harness (do not modify below this line) ----
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
