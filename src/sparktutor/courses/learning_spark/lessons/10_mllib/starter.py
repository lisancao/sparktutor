"""
Machine Learning with MLlib - Starter Code

Implement the `build_pipeline` function that:
1. Creates a sample housing dataset with categorical and numeric features
2. Splits into train/test sets (80/20)
3. Builds a Pipeline with StringIndexer, VectorAssembler, RandomForestRegressor
4. Trains the pipeline on training data
5. Evaluates RMSE and R2 on test predictions
6. Maps the forest's featureImportances back to FEATURE_COLS
7. Saves the model to model_path and loads it back
8. Returns a dict with the model, predictions, metrics, importances,
   and the loaded model

The same code runs on Spark Classic and Spark Connect (pyspark.ml
supports Connect since Spark 4.0).

Adapted from the Learning Spark MLflow train.py example.
"""

from pyspark.sql import SparkSession
from pyspark.ml import Pipeline, PipelineModel
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

# Feature columns in the order the VectorAssembler combines them.
FEATURE_COLS = ["neighborhoodIndex", "conditionIndex", "bedrooms", "sqft", "age"]


def build_pipeline(spark, model_path):
    """Build and evaluate an ML pipeline for housing price prediction."""

    housing_df = spark.createDataFrame(generate_housing_data(), SCHEMA)

    # TODO: Split into train (80%) and test (20%) with seed=42
    trainDF, testDF = None, None  # Replace

    # TODO: Create StringIndexers for categorical columns
    #       "neighborhood" -> "neighborhoodIndex"
    #       "condition" -> "conditionIndex"
    neighborhood_indexer = None  # Replace
    condition_indexer = None  # Replace

    # TODO: Create a VectorAssembler combining FEATURE_COLS
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
    rmse = None  # Replace: use setMetricName("rmse").evaluate()
    r2 = None  # Replace: use setMetricName("r2").evaluate()

    # TODO: Map the forest's featureImportances to FEATURE_COLS as a dict
    #       {column name: importance}. The forest is the last pipeline stage.
    importances = None  # Replace

    # TODO: Save the fitted model to model_path (overwrite), then load it
    #       back with PipelineModel.load
    loaded_model = None  # Replace

    return {
        "model": model,
        "predictions": predictions,
        "rmse": rmse,
        "r2": r2,
        "importances": importances,
        "loaded_model": loaded_model,
        "train_count": trainDF.count(),
        "test_count": testDF.count(),
    }


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("MLlibTest")
        .master("local[*]")
        .getOrCreate())

    import os, shutil, tempfile
    tmp = tempfile.mkdtemp()
    result = build_pipeline(spark, os.path.join(tmp, "price_model"))
    assert result is not None, "Function returned None"
    assert result["model"] is not None, "Model is None"
    assert result["predictions"] is not None, "Predictions is None"
    assert result["rmse"] is not None, "RMSE is None"
    assert result["r2"] is not None, "R2 is None"
    assert result["rmse"] > 0, f"RMSE should be positive, got {result['rmse']}"
    assert 0 < result["r2"] <= 1, f"R2 should be between 0 and 1, got {result['r2']}"

    imp = result["importances"]
    assert imp is not None and set(imp) == set(FEATURE_COLS), f"importances should cover FEATURE_COLS, got {imp}"
    assert abs(sum(imp.values()) - 1.0) < 1e-6, "Random forest importances should sum to 1"
    assert max(imp, key=imp.get) in ("sqft", "neighborhoodIndex"), \
        f"sqft or neighborhood should matter most for price, got {imp}"

    assert result["loaded_model"] is not None, "loaded_model is None"
    sample = result["predictions"].select("neighborhood", "condition", "bedrooms", "sqft", "age", "price")
    before = sorted(r["prediction"] for r in result["model"].transform(sample).collect())
    after = sorted(r["prediction"] for r in result["loaded_model"].transform(sample).collect())
    assert before == after, "The loaded model should predict exactly what the trained model predicts"
    print(f"Training samples: {result['train_count']}")
    print(f"Test samples: {result['test_count']}")
    print(f"RMSE: {result['rmse']:.2f}")
    print(f"R2: {result['r2']:.4f}")
    print("Feature importances:")
    for col_name, value in sorted(imp.items(), key=lambda kv: -kv[1]):
        print(f"  {col_name:<18} {value:.3f}")
    print("\nSample predictions:")
    result["predictions"].select("neighborhood", "condition", "bedrooms",
                                  "sqft", "age", "price", "prediction").show(10)
    print("All tests passed!")
    shutil.rmtree(tmp, ignore_errors=True)
    spark.stop()
