"""
VARIANT Basics - Exercise

Load the drifting order events (the same files as the JSON drift lesson)
without writing a schema: each record becomes one VARIANT value. Then
profile which keys and types really occur, normalize the fields that
changed shape, and explode the nested items array.
"""

from pyspark.sql import SparkSession, functions as F


def load_events(spark, path):
    """Each JSON line as one VARIANT column `v`, malformed lines kept in `_bad`.

    Also adds `file` (the file name). Cached, so `_bad` can be queried on its own.
    """
    # TODO 1: spark.read with the options singleVariantColumn = "v" and
    #   columnNameOfCorruptRecord = "_bad", THEN .schema("v VARIANT, _bad STRING")
    #   (in classic PySpark the order matters), then .json(path); add "file"
    #   from _metadata.file_name and .cache()
    return None


def key_profile(spark, ev):
    """Top-level keys: key, n (rows that have it), types (sorted base type names)."""
    ev.createOrReplaceTempView("ev")
    # TODO 2: return spark.sql(...) over
    #   FROM ev, LATERAL variant_explode(v)
    #   grouped by key, with count(*) AS n and
    #   sort_array(collect_set(regexp_extract(schema_of_variant(value), '^[A-Z]+', 0))) AS types,
    #   ordered by key
    return None


def normalize(ev):
    """One typed row per good record: event_type, user_id, plan, amount, ts, file."""
    def get(path, type_):
        return F.try_variant_get("v", path, type_)

    # TODO 3: keep rows where _bad is NULL and select, with get(...):
    #   event_type = coalesce of "$.event_type" and "$.event" (string)
    #   user_id    = coalesce of "$.user.id" and "$.user_id" (bigint)
    #   plan       = "$.user.plan" (string)
    #   amount     = coalesce of "$.amount" and "$.amount.value" (double)
    #   ts         = "$.ts" as "timestamp"
    #   file
    return None


def item_rows(spark, ev):
    """One row per item (sku, qty), plus one row of NULLs per record without items."""
    ev.createOrReplaceTempView("ev")
    # TODO 4: return spark.sql(...) selecting item.value:sku::string AS sku and
    #   item.value:qty::int AS qty
    #   FROM ev, LATERAL variant_explode_outer(v:items) AS item
    return None


# ---- Test harness ----
if __name__ == "__main__":
    import glob
    import json
    from collections import Counter

    spark = (SparkSession.builder
             .appName("VariantBasics")
             .master("local[*]")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    EVENTS = "data/messy/events"

    # Expected answers from plain Python
    amounts, qty, n_items, no_items, good = [], Counter(), 0, 0, 0
    for fname in sorted(glob.glob(f"{EVENTS}/*.json")):
        for line in open(fname):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            good += 1
            a = rec["amount"]
            amounts.append(float(a["value"]) if isinstance(a, dict) else float(a))
            if "items" in rec:
                for it in rec["items"]:
                    qty[it["sku"]] += it["qty"]
                    n_items += 1
            else:
                no_items += 1

    try:
        ev = load_events(spark, EVENTS)
        assert ev is not None, "load_events() returned None: complete TODO 1"
        assert dict(ev.dtypes).get("v") == "variant", f"v should be a variant column, got {ev.dtypes}"
        assert "_bad" in ev.columns and "file" in ev.columns, f"ev needs _bad and file columns, got {ev.columns}"
        assert ev.count() == 61, f"Expected 61 rows, one per line, got {ev.count()}"
        bad = ev.filter(F.col("_bad").isNotNull()).select("v", "_bad", "file").collect()
        assert len(bad) == 1 and bad[0]["v"] is None and bad[0]["file"] == "events_2026-10-03.json", (
            f"Expected the one truncated day 3 line in _bad (with v NULL), got {bad}. Pass the schema "
            "'v VARIANT, _bad STRING' and the option columnNameOfCorruptRecord")

        profile = key_profile(spark, ev)
        assert profile is not None, "key_profile() returned None: complete TODO 2"
        got = {r["key"]: (r["n"], list(r["types"])) for r in profile.collect()}
        want = {
            "amount": (60, ["DECIMAL", "OBJECT", "STRING"]),
            "event": (40, ["STRING"]),
            "event_type": (20, ["STRING"]),
            "items": (40, ["ARRAY"]),
            "ts": (60, ["STRING"]),
            "user": (40, ["OBJECT"]),
            "user_id": (20, ["BIGINT"]),
        }
        assert got == want, (
            f"Key profile should be {want}, got {got}. Use LATERAL variant_explode(v), and the leading "
            "capital letters of schema_of_variant(value) as the type name")

        norm = normalize(ev)
        assert norm is not None, "normalize() returned None: complete TODO 3"
        assert norm.columns == ["event_type", "user_id", "plan", "amount", "ts", "file"], f"columns: {norm.columns}"
        assert dict(norm.dtypes)["ts"] == "timestamp", f"ts should be a timestamp, got {dict(norm.dtypes)['ts']}"
        norm = norm.cache()
        assert norm.count() == good, f"Expected {good} normalized rows (malformed one excluded), got {norm.count()}"
        nulls = {c: norm.filter(F.col(c).isNull()).count() for c in ["event_type", "user_id", "amount", "ts"]}
        assert all(v == 0 for v in nulls.values()), (
            f"NULLs after normalizing: {nulls}. Try the new path first, then the old one, with coalesce; "
            "amount is $.amount (number or string) or $.amount.value (object)")
        total = round(norm.agg(F.sum("amount")).first()[0], 2)
        assert total == round(sum(amounts), 2), f"Sum of amounts should be {round(sum(amounts), 2)}, got {total}"

        items = item_rows(spark, ev)
        assert items is not None, "item_rows() returned None: complete TODO 4"
        n = items.count()
        assert n == n_items + no_items + 1, (
            f"Expected {n_items} item rows plus {no_items + 1} rows of NULLs (records without items, and the "
            f"malformed one), got {n}. Use variant_explode_outer, not variant_explode")
        got_qty = sorted((r["sku"], r["qty"]) for r in
                         items.filter("sku IS NOT NULL").groupBy("sku").agg(F.sum("qty").alias("qty")).collect())
        assert got_qty == sorted(qty.items()), f"Quantity per SKU should be {sorted(qty.items())}, got {got_qty}"

        print("Key profile:")
        profile.show(truncate=False)
        print("Normalized events:")
        norm.orderBy("ts").filter(F.minute("ts") == 0).show(truncate=False)
        print("Items per SKU:")
        items.filter("sku IS NOT NULL").groupBy("sku").agg(F.sum("qty").alias("qty")).orderBy("sku").show()
        print("All tests passed!")
    finally:
        spark.stop()
