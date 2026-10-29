"""
JSON Drift and Quarantine - Exercise

Three days of order events whose shape keeps changing:
- day 1: {"event", "user_id", "amount": number, "ts"}
- day 2: "user" becomes an object, "amount" is sometimes a string, "items" appears
- day 3: "event" is renamed "event_type", "amount" becomes {"value", "currency"},
         "user" gains "geo", and the last line is truncated

Read them with one explicit schema, quarantine what cannot be parsed, and
build one clean `silver` table out of every shape.
"""

from pyspark.sql import SparkSession, functions as F

# One schema that covers every day. The field whose type drifts (amount)
# is declared STRING: Spark then keeps whatever is there, numbers, strings
# or a whole JSON object, as text, and we decide how to read it.
EVENT_SCHEMA = """
    event STRING,
    event_type STRING,
    user_id BIGINT,
    user STRUCT<id: BIGINT, plan: STRING, geo: STRUCT<country: STRING>>,
    amount STRING,
    items ARRAY<STRUCT<sku: STRING, qty: INT>>,
    ts TIMESTAMP,
    _corrupt STRING
"""


def read_events(spark, path):
    """Read the event files with EVENT_SCHEMA, keeping malformed lines in _corrupt.

    Adds a `file` column (the file name) and caches the result, so the
    corrupt column can be queried on its own.
    """
    # TODO 1: spark.read.schema(EVENT_SCHEMA), mode PERMISSIVE, the option
    #   columnNameOfCorruptRecord set to "_corrupt", .json(path); then add
    #   "file" from _metadata.file_name and .cache() the result
    return None


def silver_and_quarantine(raw):
    """Split `raw` into (silver, quarantine).

    silver:     event_type, user_id, plan, country, amount (double), ts, items, file
                for every record that parsed
    quarantine: file, _corrupt for every record that did not
    """
    # TODO 2: amount is a STRING holding "12.5", 12.5 or '{"value": 12.5, ...}'.
    #   coalesce two readings: F.col("amount").try_cast("double") and
    #   F.get_json_object("amount", "$.value").try_cast("double")
    amount = None

    # TODO 3: silver = rows where _corrupt is NULL, with
    #   event_type = coalesce(event_type, event)
    #   user_id    = coalesce(user.id, user_id)
    #   plan = user.plan, country = user.geo.country, amount, ts, items, file
    #   quarantine = rows where _corrupt is not NULL: file, _corrupt
    silver = None
    quarantine = None
    return silver, quarantine


def items_long(silver):
    """One row per (event, item): ts, user_id, sku, qty. Events without items keep one row of NULLs."""
    # TODO 4: select ts, user_id and F.inline_outer("items")
    return None


def qty_per_sku(items):
    """Total quantity per SKU, ignoring the NULL rows: sku, qty, sorted by sku."""
    # TODO 5: drop rows with a NULL sku, sum qty per sku, order by sku
    return None


def parse_embedded(spark, path):
    """The JSON lines inside app.log, parsed with a schema inferred by schema_of_json."""
    # TODO 6: read `path` as text and keep lines starting with "{";
    #   take one line as a sample, get its DDL with
    #   spark.range(1).select(F.schema_of_json(F.lit(sample))).first()[0]
    #   (schema_of_json needs a literal, not a column), then
    #   select F.from_json("value", ddl).alias("j") and expand it with "j.*"
    return None


# ---- Test harness ----
if __name__ == "__main__":
    import glob
    import json
    import os
    from collections import Counter

    spark = (SparkSession.builder
             .appName("JsonDrift")
             .master("local[*]")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    EVENTS = "data/messy/events"

    # The expected answers, computed from the files with plain Python
    lines_per_file, bad_per_file, amounts, qty = Counter(), Counter(), [], Counter()
    n_items = 0
    for fname in sorted(glob.glob(f"{EVENTS}/*.json")):
        name = os.path.basename(fname)
        for line in open(fname):
            lines_per_file[name] += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                bad_per_file[name] += 1
                continue
            a = rec["amount"]
            amounts.append(float(a["value"]) if isinstance(a, dict) else float(a))
            for it in rec.get("items", []):
                qty[it["sku"]] += it["qty"]
                n_items += 1

    try:
        raw = read_events(spark, EVENTS)
        assert raw is not None, "read_events() returned None: complete TODO 1"
        assert "_corrupt" in raw.columns and "file" in raw.columns, (
            f"raw needs the _corrupt and file columns, got {raw.columns}")
        assert raw.count() == 61, f"Expected 61 records (one per line), got {raw.count()}"

        result = silver_and_quarantine(raw)
        assert result is not None, "silver_and_quarantine() returned None: complete TODOs 2 and 3"
        silver, quarantine = result
        assert silver is not None and quarantine is not None, (
            "silver_and_quarantine() must return two DataFrames: complete TODOs 2 and 3")
        assert silver.columns == ["event_type", "user_id", "plan", "country", "amount", "ts", "items", "file"], (
            f"silver columns are {silver.columns}")
        silver = silver.cache()

        got = {r["file"]: (r["parsed"], r["quarantined"]) for r in
               raw.groupBy("file").agg(
                   F.count(F.when(F.col("_corrupt").isNull(), 1)).alias("parsed"),
                   F.count("_corrupt").alias("quarantined")).collect()}
        want = {f: (lines_per_file[f] - bad_per_file[f], bad_per_file[f]) for f in lines_per_file}
        assert got == want, f"(parsed, quarantined) per file should be {want}, got {got}"

        n_silver, n_quarantine = silver.count(), quarantine.count()
        assert n_silver + n_quarantine == sum(lines_per_file.values()), (
            f"Rows lost: {n_silver} silver + {n_quarantine} quarantined != {sum(lines_per_file.values())} lines")
        bad = quarantine.collect()
        assert len(bad) == 1 and bad[0]["file"] == "events_2026-10-03.json" and bad[0]["_corrupt"].startswith('{"event_type"'), (
            f"The quarantine should hold the truncated day 3 line with its raw text, got {bad}")

        missing = {c: silver.filter(F.col(c).isNull()).count() for c in ["event_type", "user_id", "amount", "ts"]}
        assert all(v == 0 for v in missing.values()), (
            f"NULLs in silver: {missing}. Use coalesce across the old and new field names, and read amount "
            "both as a number (try_cast) and as {{value: ...}} (get_json_object(amount, '$.value'))")
        total = round(silver.agg(F.sum("amount")).first()[0], 2)
        assert total == round(sum(amounts), 2), f"Sum of amounts should be {round(sum(amounts), 2)}, got {total}"
        countries = silver.filter(F.col("country").isNotNull()).count()
        assert countries == 20, f"Only day 3 has user.geo.country: expected 20 rows with a country, got {countries}"

        items = items_long(silver)
        assert items is not None, "items_long() returned None: complete TODO 4"
        no_items = silver.filter(F.col("items").isNull()).count()
        n_rows = items.count()
        assert n_rows == n_items + no_items, (
            f"items_long should have one row per item ({n_items}) plus one per event without items ({no_items}), "
            f"got {n_rows}. Use inline_outer (or explode_outer), not inline/explode")

        per_sku = qty_per_sku(items)
        assert per_sku is not None, "qty_per_sku() returned None: complete TODO 5"
        got_qty = [(r["sku"], r["qty"]) for r in per_sku.collect()]
        assert got_qty == sorted(qty.items()), f"Quantity per SKU should be {sorted(qty.items())}, got {got_qty}"

        emb = parse_embedded(spark, "data/messy/logs/app.log")
        assert emb is not None, "parse_embedded() returned None: complete TODO 6"
        types = dict(emb.dtypes)
        assert emb.count() == 20, f"app.log has 20 JSON lines, got {emb.count()}"
        assert types.get("order") == "bigint" and types.get("ms") == "bigint", (
            f"order and ms should be inferred as bigint by schema_of_json, got {types}")
        assert emb.filter(F.col("level").isNull()).count() == 0, "Every JSON line has a level"

        print("Records per file:")
        raw.groupBy("file").agg(
            F.count("*").alias("lines"),
            F.count(F.when(F.col("_corrupt").isNull(), 1)).alias("parsed"),
            F.count("_corrupt").alias("quarantined")).orderBy("file").show(truncate=False)
        print("Silver, one row from each day:")
        silver.orderBy("ts").filter(F.minute("ts") == 0).drop("items").show(truncate=False)
        print("Quarantine:")
        quarantine.show(truncate=False)
        print("Quantity per SKU:")
        per_sku.show()
        print("JSON inside app.log:")
        emb.show(3)
        print("All tests passed!")
    finally:
        spark.stop()
