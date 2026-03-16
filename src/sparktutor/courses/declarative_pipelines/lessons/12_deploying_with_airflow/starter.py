"""
ShopStream Airflow Pipeline — Starter Code

Build the DAG configuration, task runner, and full pipeline executor
that would integrate with Apache Airflow.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType


def build_dag_config():
    """
    Return a dict describing the ShopStream Airflow DAG.

    Keys:
      - dag_id: "shopstream_daily"
      - schedule: cron for 2 AM UTC daily
      - retries: 3
      - retry_delay_minutes: 5
      - tasks: list of task names in the pipeline
      - dependencies: dict mapping task → list of upstream task names
    """

    # TODO: Return the DAG config dict
    pass


def run_pipeline_task(spark, task_name, execution_date, data_dir, **kwargs):
    """
    Run a single pipeline task by name.

    Tasks:
      - "bronze_clicks": read CSV, add _ingested_at, dedup by event_id → row count
      - "bronze_payments": read JSON, add _ingested_at → row count
      - "silver_clicks": read bronze_clicks view, cast timestamp,
        quarantine invalid → (valid_count, quarantine_count)
      - "silver_payments": read bronze_payments view, cast amount to double → row count
      - "gold_revenue": read silver_payments view, groupBy date+category,
        sum amount → row count
      - "monitor": build report from kwargs (bronze_rows, silver_valid,
        silver_quarantine, gold_rows) → report dict

    Returns: task-specific result (int, tuple, or dict)
    """

    if task_name == "bronze_clicks":
        # TODO: Read clicks CSV with all-string schema, add _ingested_at,
        #       dedup by event_id, register as temp view
        pass

    elif task_name == "bronze_payments":
        # TODO: Read payments JSON, add _ingested_at, register as temp view
        pass

    elif task_name == "silver_clicks":
        # TODO: Read bronze_clicks view, cast timestamp, split valid/quarantine,
        #       register valid as temp view
        pass

    elif task_name == "silver_payments":
        # TODO: Read bronze_payments view, cast amount to double,
        #       filter nulls, register as temp view
        pass

    elif task_name == "gold_revenue":
        # TODO: Read silver_payments view, groupBy date+category, sum amount,
        #       register as temp view
        pass

    elif task_name == "monitor":
        # TODO: Build report dict from kwargs:
        #       bronze_rows, silver_valid, silver_quarantine, gold_rows, quality_score
        pass

    else:
        raise ValueError(f"Unknown task: {task_name}")


def run_full_pipeline(spark, data_dir, execution_date):
    """
    Execute all tasks in dependency order, collect results, return
    the monitoring report.

    Returns: dict with keys bronze_rows, silver_valid, silver_quarantine,
             gold_rows, quality_score
    """

    # TODO: Run tasks in order: bronze_clicks, bronze_payments,
    #       silver_clicks, silver_payments, gold_revenue, monitor
    # TODO: Pass results between steps
    # TODO: Return the monitor report
    pass


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    import tempfile
    import os
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
    assert "bronze_rows" in report, "Missing bronze_rows in report"
    assert "silver_valid" in report, "Missing silver_valid in report"
    assert "silver_quarantine" in report, "Missing silver_quarantine in report"
    assert "gold_rows" in report, "Missing gold_rows in report"
    assert "quality_score" in report, "Missing quality_score in report"
    assert report["bronze_rows"] >= 2, f"Expected >= 2 bronze rows, got {report['bronze_rows']}"
    assert report["silver_quarantine"] >= 1, f"Expected >= 1 quarantine rows, got {report['silver_quarantine']}"
    assert 0 <= report["quality_score"] <= 1, f"quality_score out of range: {report['quality_score']}"

    print("\nAll tests passed!")
    print(f"Pipeline report: {report}")
    spark.stop()
