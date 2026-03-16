"""
ShopStream Airflow Pipeline — Solution

DAG configuration, task runner, and full pipeline executor.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType
import os


def build_dag_config():
    """Return DAG configuration dict for ShopStream."""
    return {
        "dag_id": "shopstream_daily",
        "schedule": "0 2 * * *",
        "retries": 3,
        "retry_delay_minutes": 5,
        "tasks": [
            "bronze_clicks", "bronze_payments",
            "silver_clicks", "silver_payments",
            "gold_revenue", "monitor",
        ],
        "dependencies": {
            "silver_clicks": ["bronze_clicks", "bronze_payments"],
            "silver_payments": ["bronze_payments"],
            "gold_revenue": ["silver_clicks", "silver_payments"],
            "monitor": ["gold_revenue"],
        },
    }


def run_pipeline_task(spark, task_name, execution_date, data_dir, **kwargs):
    """Run a single pipeline task by name."""

    if task_name == "bronze_clicks":
        click_schema = StructType([
            StructField("event_id", StringType()),
            StructField("user_id", StringType()),
            StructField("product_id", StringType()),
            StructField("event_type", StringType()),
            StructField("timestamp", StringType()),
        ])
        csv_path = os.path.join(data_dir, "clicks.csv")
        raw = spark.read.csv(csv_path, header=True, schema=click_schema)
        bronze = (raw
            .withColumn("_ingested_at", f.current_timestamp())
            .dropDuplicates(["event_id"]))
        bronze.createOrReplaceTempView("bronze_clicks")
        return bronze.count()

    elif task_name == "bronze_payments":
        json_path = os.path.join(data_dir, "payments.json")
        raw = spark.read.json(json_path)
        bronze = raw.withColumn("_ingested_at", f.current_timestamp())
        bronze.createOrReplaceTempView("bronze_payments")
        return bronze.count()

    elif task_name == "silver_clicks":
        bronze = spark.table("bronze_clicks")
        with_ts = bronze.withColumn(
            "parsed_ts", f.to_timestamp("timestamp"))
        valid = with_ts.filter(f.col("parsed_ts").isNotNull())
        quarantine = with_ts.filter(f.col("parsed_ts").isNull())
        valid.createOrReplaceTempView("silver_clicks")
        return (valid.count(), quarantine.count())

    elif task_name == "silver_payments":
        bronze = spark.table("bronze_payments")
        casted = bronze.withColumn("amount_double", f.col("amount").cast(DoubleType()))
        valid = casted.filter(f.col("amount_double").isNotNull())
        valid.createOrReplaceTempView("silver_payments")
        return valid.count()

    elif task_name == "gold_revenue":
        silver = spark.table("silver_payments")
        gold = (silver
            .groupBy("date", "category")
            .agg(f.sum("amount_double").alias("total_revenue")))
        gold.createOrReplaceTempView("gold_revenue")
        return gold.count()

    elif task_name == "monitor":
        bronze_rows = kwargs.get("bronze_rows", 0)
        silver_valid = kwargs.get("silver_valid", 0)
        silver_quarantine = kwargs.get("silver_quarantine", 0)
        gold_rows = kwargs.get("gold_rows", 0)
        total = silver_valid + silver_quarantine
        quality_score = silver_valid / total if total > 0 else 1.0
        return {
            "bronze_rows": bronze_rows,
            "silver_valid": silver_valid,
            "silver_quarantine": silver_quarantine,
            "gold_rows": gold_rows,
            "quality_score": quality_score,
        }

    else:
        raise ValueError(f"Unknown task: {task_name}")


def run_full_pipeline(spark, data_dir, execution_date):
    """Execute all tasks in dependency order, return monitoring report."""

    bronze_click_rows = run_pipeline_task(
        spark, "bronze_clicks", execution_date, data_dir)
    bronze_payment_rows = run_pipeline_task(
        spark, "bronze_payments", execution_date, data_dir)

    silver_click_result = run_pipeline_task(
        spark, "silver_clicks", execution_date, data_dir)
    silver_valid, silver_quarantine = silver_click_result

    silver_payment_rows = run_pipeline_task(
        spark, "silver_payments", execution_date, data_dir)

    gold_rows = run_pipeline_task(
        spark, "gold_revenue", execution_date, data_dir)

    report = run_pipeline_task(
        spark, "monitor", execution_date, data_dir,
        bronze_rows=bronze_click_rows + bronze_payment_rows,
        silver_valid=silver_valid + silver_payment_rows,
        silver_quarantine=silver_quarantine,
        gold_rows=gold_rows,
    )

    return report


# ---- Test harness ----
if __name__ == "__main__":
    import tempfile
    import json

    spark = (SparkSession.builder
        .appName("AirflowTest")
        .master("local[*]")
        .config("spark.sql.shuffle.partitions", "4")
        .getOrCreate())

    tmp = tempfile.mkdtemp()
    clicks_path = os.path.join(tmp, "clicks.csv")
    with open(clicks_path, "w") as fh:
        fh.write("event_id,user_id,product_id,event_type,timestamp\n")
        fh.write("e1,u1,p1,click,2024-01-15 10:00:00\n")
        fh.write("e2,u2,p2,click,2024-01-15 11:00:00\n")
        fh.write("e3,u3,p1,click,invalid_timestamp\n")
        fh.write("e1,u1,p1,click,2024-01-15 10:00:00\n")

    payments_path = os.path.join(tmp, "payments.json")
    with open(payments_path, "w") as fh:
        for row in [
            {"payment_id": "pay1", "user_id": "u1", "amount": "29.99",
             "category": "Electronics", "date": "2024-01-15"},
            {"payment_id": "pay2", "user_id": "u2", "amount": "49.99",
             "category": "Home", "date": "2024-01-15"},
            {"payment_id": "pay3", "user_id": "u3", "amount": "bad_amount",
             "category": "Electronics", "date": "2024-01-15"},
        ]:
            fh.write(json.dumps(row) + "\n")

    dag_config = build_dag_config()
    assert dag_config is not None, "build_dag_config returned None"
    assert dag_config["dag_id"] == "shopstream_daily"
    assert dag_config["schedule"] == "0 2 * * *"
    assert dag_config["retries"] == 3
    assert "bronze_clicks" in dag_config["tasks"]
    assert "monitor" in dag_config["tasks"]
    assert "bronze_clicks" in dag_config["dependencies"].get("silver_clicks", [])
    print("DAG config OK")

    report = run_full_pipeline(spark, tmp, "2024-01-15")
    assert report is not None, "run_full_pipeline returned None"
    assert "bronze_rows" in report
    assert "silver_valid" in report
    assert "silver_quarantine" in report
    assert "gold_rows" in report
    assert "quality_score" in report
    assert report["bronze_rows"] >= 2, f"Expected >= 2 bronze rows, got {report['bronze_rows']}"
    assert report["silver_quarantine"] >= 1, f"Expected >= 1 quarantine rows, got {report['silver_quarantine']}"
    assert 0 <= report["quality_score"] <= 1, f"quality_score out of range: {report['quality_score']}"

    print("\nAll tests passed!")
    print(f"Pipeline report: {report}")
    spark.stop()
