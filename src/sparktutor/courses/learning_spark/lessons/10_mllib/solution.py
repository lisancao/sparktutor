"""
Machine Learning with MLlib - Solution

Complete ML pipeline for housing price prediction, with feature
importances and a save/load round trip. Runs unchanged on Spark Connect.
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

    (trainDF, testDF) = housing_df.randomSplit([0.8, 0.2], seed=42)

    neighborhood_indexer = StringIndexer(
        inputCol="neighborhood", outputCol="neighborhoodIndex", handleInvalid="skip"
    )
    condition_indexer = StringIndexer(
        inputCol="condition", outputCol="conditionIndex", handleInvalid="skip"
    )

    assembler = VectorAssembler(
        inputCols=FEATURE_COLS,
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

    forest = model.stages[-1]
    importances = dict(zip(FEATURE_COLS, forest.featureImportances.toArray().tolist()))

    model.write().overwrite().save(model_path)
    loaded_model = PipelineModel.load(model_path)

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


# ---- Test harness ----
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
