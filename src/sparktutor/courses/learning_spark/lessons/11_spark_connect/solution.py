"""
Spark Connect - Solution

A small report built only from Connect-safe APIs: JSON parsed from a
DataFrame of strings, an aggregation, consecutive ranks without the RDD
API, a Python UDF, and a plan captured without touching the JVM.
"""

import contextlib
import io

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.utils import is_remote


RAW_ORDERS = [
    ('{"order_id": 1, "region": "West", "amount": 120.0}',),
    ('{"order_id": 2, "region": "East", "amount": 80.5}',),
    ('{"order_id": 3, "region": "West", "amount": 42.0}',),
    ('{"order_id": 4, "region": "North", "amount": 300.0}',),
    ('{"order_id": 5, "region": "East", "amount": 19.5}',),
    ('{"order_id": 6, "region": "South", "amount": 55.0}',),
]

ORDER_SCHEMA = "order_id INT, region STRING, amount DOUBLE"


def plan_text(df, mode="formatted"):
    """Return what df.explain(mode) prints. Works in Classic and Connect."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        df.explain(mode=mode)
    return buf.getvalue()


def connect_report(spark):
    """Build a revenue report using only APIs that work over Spark Connect."""

    mode = "connect" if is_remote() else "classic"

    raw = spark.createDataFrame(RAW_ORDERS, "value STRING")
    orders = spark.read.schema(ORDER_SCHEMA).json(raw)

    revenue = (orders
        .groupBy("region")
        .agg(f.sum("amount").alias("revenue"), f.count("*").alias("orders"))
        .orderBy(f.col("revenue").desc()))

    ranked = revenue.zipWithIndex("rank")

    @f.udf("string")
    def tier(revenue):
        return "gold" if revenue >= 150 else "standard"

    report = ranked.withColumn("tier", tier("revenue"))

    plan = plan_text(report)

    as_json = report.toJSON()

    return {
        "mode": mode,
        "orders": orders,
        "report": report,
        "plan": plan,
        "as_json": as_json,
    }


# ---- Test harness ----
if __name__ == "__main__":
    import json

    # spark.api.mode=connect starts a local Spark Connect server and returns
    # a Connect session, even under spark-submit.
    spark = (SparkSession.builder
        .appName("SparkConnectTest")
        .master("local[2]")
        .config("spark.api.mode", "connect")
        .getOrCreate())

    result = connect_report(spark)
    assert result is not None, "Function returned None"
    for key in ["mode", "orders", "report", "plan", "as_json"]:
        assert result.get(key) is not None, f"{key} is missing or None"

    assert result["mode"] == "connect", f"Expected a Spark Connect session, got {result['mode']}"
    assert dict(result["orders"].dtypes) == {"order_id": "int", "region": "string", "amount": "double"}, \
        f"orders schema wrong: {result['orders'].dtypes}"

    rows = result["report"].orderBy("rank").collect()
    assert [r["region"] for r in rows] == ["North", "West", "East", "South"], \
        f"Regions should be ranked by revenue, got {[r['region'] for r in rows]}"
    assert [r["rank"] for r in rows] == [0, 1, 2, 3], f"Ranks should be 0..3, got {[r['rank'] for r in rows]}"
    assert [r["tier"] for r in rows] == ["gold", "gold", "standard", "standard"], \
        f"Tiers wrong: {[r['tier'] for r in rows]}"

    assert "HashAggregate" in result["plan"], "The plan should show the aggregation"

    first_json = json.loads(result["as_json"].orderBy("value").first()[0])
    assert {"region", "revenue", "orders", "rank", "tier"} <= set(first_json), \
        f"toJSON rows should carry every report column, got {first_json}"

    print(f"Session mode: {result['mode']} (Spark {spark.version})")
    print("Revenue report:")
    result["report"].orderBy("rank").show()
    print("As JSON (DataFrame of strings under Connect):")
    result["as_json"].show(truncate=False)
    print("All tests passed!")
    spark.stop()
