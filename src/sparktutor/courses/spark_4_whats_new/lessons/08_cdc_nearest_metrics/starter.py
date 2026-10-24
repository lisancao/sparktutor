"""
CDC, NEAREST BY, time_bucket and Metric Views - Starter Code

Implement `changes_between(...)` and `whats_new_tour(spark)`:
1. Save SNAPSHOT_V1 as the table `inventory`; try
   `SELECT * FROM inventory CHANGES FROM VERSION 0` and
   spark.read.option("startingVersion", "0").changes("inventory");
   record each PySparkException's getCondition() under "sql" / "dataframe"
2. changes_between(): diff two snapshots into a changelog with
   _change_type (insert / delete / update_preimage / update_postimage),
   _commit_version and _commit_timestamp
3. NEAREST BY: the 2 closest warehouses per store in SQL
   (EXACT NEAREST 2 BY DISTANCE <euclidean distance>), and the single
   closest via stores.nearestByJoin(..., "exact", "similarity") on the
   negated distance
4. time_bucket: sum(qty) per 15-minute bucket; distinct 30-minute buckets
   with origin TIMESTAMP_NTZ '2024-06-01 09:10:00'
5. Metric view `order_metrics` over `orders_t` (filter qty > 0;
   dimensions region, product; measures units = sum(qty),
   revenue = sum(qty * price), avg_price = avg(price))
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
    """Approximate the CDC changelog between two snapshots of a table."""
    cols = [c for c in before.columns if c != key]
    joined = before.alias("b").join(after.alias("a"), on=key, how="full_outer")

    # TODO: `same` is True when every non-key column matches (use eqNullSafe)
    same = sf.lit(True)
    in_b = sf.col(f"b.{cols[0]}").isNotNull()
    in_a = sf.col(f"a.{cols[0]}").isNotNull()

    def side(prefix, change_type, cond):
        return joined.filter(cond).select(
            key, *[sf.col(f"{prefix}.{c}").alias(c) for c in cols],
            sf.lit(change_type).alias("_change_type"),
        )

    # TODO: union inserts (in a, not in b), deletes (in b, not in a), and for
    #       changed rows an update_preimage (from b) and update_postimage (from a)
    changes = side("a", "insert", in_a & ~in_b)  # Extend with unionByName(...)

    # TODO: add _commit_version (long) and _commit_timestamp columns
    return changes


def whats_new_tour(spark):
    """CDC attempt + approximation, NEAREST BY, time_bucket, metric view."""

    spark.sql("DROP TABLE IF EXISTS inventory")
    spark.createDataFrame(SNAPSHOT_V1, "id int, item string, qty int") \
        .write.format("parquet").saveAsTable("inventory")

    # TODO 1: try both CDC entry points (call .collect()), store getCondition()
    cdc_errors = {}

    v1 = spark.createDataFrame(SNAPSHOT_V1, "id int, item string, qty int")
    v2 = spark.createDataFrame(SNAPSHOT_V2, "id int, item string, qty int")
    changelog = changes_between(spark, v1, v2, "id", 2).orderBy("id", "_change_type")

    spark.createDataFrame(WAREHOUSES, "warehouse string, wx double, wy double") \
        .createOrReplaceTempView("warehouses")
    spark.createDataFrame(STORES, "store string, sx double, sy double") \
        .createOrReplaceTempView("stores")

    # TODO 3a: SELECT s.store, w.warehouse, round(<distance>, 2) AS dist
    #          FROM stores s JOIN warehouses w EXACT NEAREST 2 BY DISTANCE <distance>
    #          ORDER BY s.store, dist
    nearest_sql = None  # Replace

    # TODO 3b: stores_df.nearestByJoin(wh_df, -<distance column>, 1, "exact", "similarity")
    #          .select("store", "warehouse").orderBy("store")
    nearest_df = None  # Replace

    orders = spark.createDataFrame(
        ORDERS, "region string, product string, qty int, price double, ts timestamp_ntz"
    )
    # TODO 4: group by sf.time_bucket(sf.expr("INTERVAL 15 MINUTES"), "ts").alias("bucket"),
    #         sum qty AS qty, order by bucket
    buckets = None  # Replace
    # TODO 4b: 30-minute buckets with origin sf.expr("TIMESTAMP_NTZ '2024-06-01 09:10:00'"),
    #          aliased "b", distinct, ordered
    shifted = None  # Replace

    spark.sql("DROP VIEW IF EXISTS order_metrics")
    spark.sql("DROP TABLE IF EXISTS orders_t")
    orders.write.format("parquet").saveAsTable("orders_t")
    # TODO 5: CREATE VIEW order_metrics WITH METRICS LANGUAGE YAML AS $$ ... $$
    by_region = None   # Replace: region, measure(units) AS units, measure(revenue) AS revenue
    widget_total = None  # Replace: measure(revenue) WHERE product = 'widget'

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


# ---- Test harness (do not modify below this line) ----
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
