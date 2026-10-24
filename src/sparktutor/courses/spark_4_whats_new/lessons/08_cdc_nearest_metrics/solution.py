"""
CDC, NEAREST BY, time_bucket and Metric Views - Solution
"""

import tempfile
from datetime import datetime

from pyspark.sql import SparkSession, functions as sf
from pyspark.errors import PySparkException


SNAPSHOT_V1 = [(1, "bolt", 100), (2, "nut", 250), (3, "washer", 75)]
SNAPSHOT_V2 = [(1, "bolt", 90), (3, "washer", 75), (4, "rivet", 40)]

WAREHOUSES = [("north", 0.0, 10.0), ("east", 8.0, 0.0), ("south", 0.0, -9.0), ("west", -7.0, 2.0)]
STORES = [("s1", 1.0, 8.0), ("s2", 6.0, -1.0), ("s3", -5.0, -6.0)]

ORDERS = [
    ("east", "widget", 3, 10.0, datetime(2024, 6, 1, 9, 2)),
    ("east", "gadget", 1, 25.0, datetime(2024, 6, 1, 9, 14)),
    ("west", "widget", 5, 10.0, datetime(2024, 6, 1, 9, 16)),
    ("west", "gizmo", 2, 40.0, datetime(2024, 6, 1, 9, 31)),
    ("east", "widget", 4, 10.0, datetime(2024, 6, 1, 9, 44)),
    ("west", "widget", 0, 10.0, datetime(2024, 6, 1, 9, 50)),
]


def changes_between(spark, before, after, key, version):
    """Approximate the CDC changelog between two snapshots of a table.

    Produces the same metadata columns a CDC connector returns
    (_change_type, _commit_version, _commit_timestamp) with updates split
    into update_preimage / update_postimage rows.
    """
    cols = [c for c in before.columns if c != key]
    b = before.alias("b")
    a = after.alias("a")
    joined = b.join(a, on=key, how="full_outer")
    same = sf.lit(True)
    for c in cols:
        same = same & sf.col(f"b.{c}").eqNullSafe(sf.col(f"a.{c}"))
    in_b = sf.col(f"b.{cols[0]}").isNotNull()
    in_a = sf.col(f"a.{cols[0]}").isNotNull()

    def side(prefix, change_type, cond):
        return joined.filter(cond).select(
            key, *[sf.col(f"{prefix}.{c}").alias(c) for c in cols],
            sf.lit(change_type).alias("_change_type"),
        )

    changes = (side("a", "insert", in_a & ~in_b)
        .unionByName(side("b", "delete", in_b & ~in_a))
        .unionByName(side("b", "update_preimage", in_a & in_b & ~same))
        .unionByName(side("a", "update_postimage", in_a & in_b & ~same)))
    return (changes
        .withColumn("_commit_version", sf.lit(version).cast("long"))
        .withColumn("_commit_timestamp", sf.current_timestamp()))


def whats_new_tour(spark):
    """CDC attempt + approximation, NEAREST BY, time_bucket, metric view."""

    # 1. CDC (4.2). The built-in session catalog does not implement
    #    TableCatalog.loadChangelog(), so CHANGES fails here with a clear error.
    spark.sql("DROP TABLE IF EXISTS inventory")
    spark.createDataFrame(SNAPSHOT_V1, "id int, item string, qty int") \
        .write.format("parquet").saveAsTable("inventory")
    cdc_errors = {}
    try:
        spark.sql("SELECT * FROM inventory CHANGES FROM VERSION 0").collect()
    except PySparkException as e:
        cdc_errors["sql"] = e.getCondition()
    try:
        spark.read.option("startingVersion", "0").changes("inventory").collect()
    except PySparkException as e:
        cdc_errors["dataframe"] = e.getCondition()

    # 1b. The runnable approximation: diff two snapshots into a changelog.
    v1 = spark.createDataFrame(SNAPSHOT_V1, "id int, item string, qty int")
    v2 = spark.createDataFrame(SNAPSHOT_V2, "id int, item string, qty int")
    changelog = changes_between(spark, v1, v2, "id", 2).orderBy("id", "_change_type")

    # 2. NEAREST BY top-K join (4.2): the two closest warehouses per store.
    spark.createDataFrame(WAREHOUSES, "warehouse string, wx double, wy double") \
        .createOrReplaceTempView("warehouses")
    spark.createDataFrame(STORES, "store string, sx double, sy double") \
        .createOrReplaceTempView("stores")
    nearest_sql = spark.sql("""
        SELECT s.store, w.warehouse,
               round(sqrt(pow(s.sx - w.wx, 2) + pow(s.sy - w.wy, 2)), 2) AS dist
        FROM stores s
        JOIN warehouses w
          EXACT NEAREST 2 BY DISTANCE sqrt(pow(s.sx - w.wx, 2) + pow(s.sy - w.wy, 2))
        ORDER BY s.store, dist
    """)
    stores_df = spark.table("stores")
    wh_df = spark.table("warehouses")
    nearest_df = (stores_df.nearestByJoin(
            wh_df,
            -sf.sqrt(sf.pow(stores_df.sx - wh_df.wx, 2) + sf.pow(stores_df.sy - wh_df.wy, 2)),
            1, "exact", "similarity")
        .select("store", "warehouse").orderBy("store"))

    # 3. time_bucket (4.2): fixed-size buckets with an optional origin.
    orders = spark.createDataFrame(
        ORDERS, "region string, product string, qty int, price double, ts timestamp_ntz"
    )
    buckets = (orders
        .groupBy(sf.time_bucket(sf.expr("INTERVAL 15 MINUTES"), "ts").alias("bucket"))
        .agg(sf.sum("qty").alias("qty"))
        .orderBy("bucket"))
    shifted = (orders
        .select(sf.time_bucket(sf.expr("INTERVAL 30 MINUTES"), "ts",
                               sf.expr("TIMESTAMP_NTZ '2024-06-01 09:10:00'")).alias("b"))
        .distinct().orderBy("b"))

    # 4. Metric view (4.2): define measures once, slice by any dimension.
    spark.sql("DROP VIEW IF EXISTS order_metrics")
    spark.sql("DROP TABLE IF EXISTS orders_t")
    orders.write.format("parquet").saveAsTable("orders_t")
    spark.sql("""
        CREATE VIEW order_metrics
        WITH METRICS
        LANGUAGE YAML
        AS $$
        version: "0.1"
        source: orders_t
        filter: qty > 0
        dimensions:
          - name: region
            expr: region
          - name: product
            expr: product
        measures:
          - name: units
            expr: sum(qty)
          - name: revenue
            expr: sum(qty * price)
          - name: avg_price
            expr: avg(price)
        $$
    """)
    by_region = spark.sql("""
        SELECT region, measure(units) AS units, measure(revenue) AS revenue
        FROM order_metrics GROUP BY region ORDER BY region
    """)
    widget_total = spark.sql("""
        SELECT measure(revenue) AS revenue FROM order_metrics WHERE product = 'widget'
    """).first()["revenue"]

    return {
        "cdc_errors": cdc_errors,
        "changelog": changelog,
        "nearest_sql": nearest_sql,
        "nearest_df": nearest_df,
        "buckets": buckets,
        "shifted": shifted,
        "by_region": by_region,
        "widget_total": widget_total,
    }


# ---- Test harness ----
if __name__ == "__main__":
    warehouse = tempfile.mkdtemp(prefix="sparktutor_wh_")
    spark = (SparkSession.builder
        .appName("WhatsNewTour")
        .master("local[*]")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.warehouse.dir", warehouse)
        .getOrCreate())

    r = whats_new_tour(spark)
    assert r is not None, "Function returned None"
    assert r["cdc_errors"].get("sql") == "UNSUPPORTED_FEATURE.CHANGE_DATA_CAPTURE", r["cdc_errors"]
    assert r["cdc_errors"].get("dataframe") == "UNSUPPORTED_FEATURE.CHANGE_DATA_CAPTURE", r["cdc_errors"]
    cl = {(x["id"], x["_change_type"]): x["qty"] for x in r["changelog"].collect()}
    assert cl == {
        (1, "update_postimage"): 90, (1, "update_preimage"): 100,
        (2, "delete"): 250, (4, "insert"): 40,
    }, cl
    ns = [(x["store"], x["warehouse"]) for x in r["nearest_sql"].collect()]
    assert ns == [("s1", "north"), ("s1", "west"), ("s2", "east"), ("s2", "south"),
                  ("s3", "south"), ("s3", "west")], ns
    nd = {x["store"]: x["warehouse"] for x in r["nearest_df"].collect()}
    assert nd == {"s1": "north", "s2": "east", "s3": "south"}, nd
    b = [(x["bucket"].strftime("%H:%M"), x["qty"]) for x in r["buckets"].collect()]
    assert b == [("09:00", 4), ("09:15", 5), ("09:30", 6), ("09:45", 0)], b
    sh = [x["b"].strftime("%H:%M") for x in r["shifted"].collect()]
    assert sh == ["08:40", "09:10", "09:40"], sh
    reg = {x["region"]: (x["units"], x["revenue"]) for x in r["by_region"].collect()}
    assert reg == {"east": (8, 95.0), "west": (7, 130.0)}, reg
    assert r["widget_total"] == 120.0, r["widget_total"]
    print("CDC errors:", r["cdc_errors"])
    r["changelog"].show(truncate=False)
    r["nearest_sql"].show()
    r["buckets"].show()
    r["by_region"].show()
    print("All tests passed!")
    spark.stop()
