"""
Spark Connect - Starter Code

Implement `connect_report(spark)` using only APIs that work over Spark
Connect (no sparkContext, no RDDs, no df._jdf):
1. Record whether the session is a Connect session ("connect"/"classic")
2. Parse RAW_ORDERS (a DataFrame of JSON strings) with
   spark.read.schema(ORDER_SCHEMA).json(raw_df), which accepts a
   DataFrame on Connect since Spark 4.2
3. Aggregate revenue (sum of amount) and order count per region, highest
   revenue first
4. Number the rows 0, 1, 2, ... with DataFrame.zipWithIndex("rank"), the
   4.2 replacement for rdd.zipWithIndex()
5. Add a "tier" column with a Python UDF: "gold" if revenue >= 150,
   otherwise "standard"
6. Capture the plan with plan_text()
7. Convert the report to JSON strings with toJSON() (a DataFrame under
   Connect)

The harness starts a local Spark Connect server for you.
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

    # TODO: "connect" if is_remote() else "classic"
    mode = None  # Replace

    raw = spark.createDataFrame(RAW_ORDERS, "value STRING")

    # TODO: Parse raw with spark.read.schema(ORDER_SCHEMA).json(raw)
    orders = None  # Replace

    # TODO: Per region: sum(amount) AS revenue, count(*) AS orders,
    #       ordered by revenue descending
    revenue = None  # Replace

    # TODO: Append a 0-based "rank" column with zipWithIndex
    ranked = None  # Replace

    # TODO: Define a Python UDF returning "gold" when revenue >= 150,
    #       otherwise "standard", and add it as column "tier"
    report = None  # Replace

    # TODO: Capture the plan of report with plan_text()
    plan = None  # Replace

    # TODO: Convert report to JSON strings with toJSON()
    as_json = None  # Replace

    return {
        "mode": mode,
        "orders": orders,
        "report": report,
        "plan": plan,
        "as_json": as_json,
    }


# ---- Test harness (do not modify below this line) ----
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
