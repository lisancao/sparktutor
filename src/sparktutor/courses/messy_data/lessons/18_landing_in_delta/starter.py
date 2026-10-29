# spark-connectors: delta
"""
Landing Messy Data in Delta Lake - Exercise

Land the drifting JSON events in Delta tables: bronze keeps every raw line,
silver holds typed and cleaned events, quarantine holds the lines that do not
parse, and gold is a small daily summary. Day 1 and 2 arrive first; day 3 then
arrives with new fields, a changed amount shape and a truncated line, together
with a second delivery of day 2 that must not create duplicates.
"""

import json
import os
import re
import tempfile

from pyspark.sql import SparkSession, functions as F

EVENTS = "data/messy/events"

# The drift-absorbing schema from "JSON Drift and Quarantine"
EVENT_SCHEMA = """
    event STRING, event_type STRING, user_id BIGINT,
    user STRUCT<id: BIGINT, plan: STRING, geo: STRUCT<country: STRING>>,
    amount STRING,
    items ARRAY<STRUCT<sku: STRING, qty: INT>>,
    ts TIMESTAMP,
    _corrupt STRING
"""


def table(root, name):
    """SQL name of the Delta table stored at root/name."""
    return f"delta.`{os.path.join(root, name)}`"


def create_tables(spark, root):
    """Create the bronze, silver and quarantine tables (empty) under root."""
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS {table(root, 'bronze')} (
            record_id STRING NOT NULL, file STRING, raw STRING, ingested_at TIMESTAMP)
        USING delta""")
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS {table(root, 'silver')} (
            event_id STRING NOT NULL, kind STRING, user_id BIGINT, plan STRING,
            amount DOUBLE, ts TIMESTAMP, file STRING)
        USING delta""")
    # TODO: add the CHECK constraint positive_amount to silver. It must allow
    #       NULL amounts (Delta rejects NULL for a plain `amount > 0`).
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS {table(root, 'quarantine')} (
            record_id STRING NOT NULL, file STRING, raw STRING, reason STRING,
            quarantined_at TIMESTAMP)
        USING delta""")


def land_bronze(spark, root, files):
    """Append the lines of `files` to bronze, skipping lines that are already there.

    record_id is sha2(file name || '|' || line, 256), so a file delivered twice
    produces the same ids and MERGE inserts only the new ones.
    """
    # TODO: read the files as text; build file (from _metadata), raw, record_id
    #       (sha2 of file, "|" and raw, 256 bits) and ingested_at; drop duplicate
    #       record_ids; MERGE into bronze inserting only ids it does not have
    pass


def refine(spark, root, with_country):
    """Parse bronze into silver and quarantine.

    Silver columns: event_id (the bronze record_id), kind, user_id, plan,
    amount (double, every shape), ts, file, and from the day the producer
    started sending it, country (with_country=True). The table schema must
    evolve to take the new column. Lines that do not parse go to quarantine
    with reason 'malformed'. Running refine twice adds nothing.
    """
    # TODO: read bronze (format "delta"), parse raw with from_json(EVENT_SCHEMA)
    #       and the option {"columnNameOfCorruptRecord": "_corrupt"}
    # TODO: good rows -> silver columns (amount for every shape, like
    #       "JSON Drift and Quarantine"); add country when with_country is True
    # TODO: bad rows -> record_id, file, raw, reason 'malformed', quarantined_at
    # TODO: insert-only MERGE of each into its table on the record id; the silver
    #       MERGE needs WITH SCHEMA EVOLUTION when with_country is True
    pass


def build_gold(spark, root):
    """Rebuild gold (day, events, revenue rounded to 2 places) from silver; return it."""
    # TODO: day, events, revenue (round 2) from silver; overwrite root/gold as
    #       Delta; return it read back
    return None


def history(spark, root, name):
    """(version, operation) pairs of root/name, oldest first."""
    # TODO: DESCRIBE HISTORY, oldest first, as (version, operation) pairs
    return []


def silver_as_of(spark, root, version):
    """Silver as it was at `version` (time travel)."""
    # TODO: time travel to `version`
    return None


# ---- Test harness ----
def expected_from_json(names):
    """Parsed lines, broken lines, and revenue per day, computed with Python's json."""
    good, bad, revenue = 0, 0, {}
    for name in names:
        for line in open(os.path.join(EVENTS, name)):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            good += 1
            amt = rec["amount"]["value"] if isinstance(rec["amount"], dict) else float(rec["amount"])
            day = rec["ts"][:10]
            revenue[day] = round(revenue.get(day, 0.0) + amt, 6)
    return good, bad, {d: round(v, 2) for d, v in revenue.items()}


def error_conditions(exc):
    """Every [ERROR_CONDITION] named in an exception's message."""
    return set(re.findall(r"\[([A-Z][A-Z0-9_]+(?:\.[A-Z0-9_]+)?)\]", str(exc)))


def count(spark, root, name):
    return spark.read.format("delta").load(os.path.join(root, name)).count()


if __name__ == "__main__":
    spark = (SparkSession.builder
             .appName("LandingInDelta")
             .master("local[*]")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.shuffle.partitions", "4")
             .getOrCreate())
    spark.sparkContext.setLogLevel("OFF")  # failed writes below are expected; keep the log quiet

    root = tempfile.mkdtemp(prefix="lakehouse_")
    days = [os.path.join(EVENTS, n) for n in sorted(os.listdir(EVENTS))]
    names = [os.path.basename(d) for d in days]

    try:
        create_tables(spark, root)
        for name in ("bronze", "silver", "quarantine"):
            assert os.path.isdir(os.path.join(root, name, "_delta_log")), (
                f"{name} is not a Delta table: create it with CREATE TABLE ... USING delta at {name}/")
        props = {r["key"]: r["value"] for r in
                 spark.sql(f"SHOW TBLPROPERTIES {table(root, 'silver')}").collect()}
        assert "delta.constraints.positive_amount" in props, (
            "silver needs the CHECK constraint positive_amount (amount IS NULL OR amount > 0)")
        assert "is null" in props["delta.constraints.positive_amount"].lower(), (
            "positive_amount must allow NULL amounts: Delta rejects a row when the check is NULL, "
            f"so write (amount IS NULL OR amount > 0); got {props['delta.constraints.positive_amount']}")

        # Day 1 and day 2
        land_bronze(spark, root, days[:2])
        refine(spark, root, with_country=False)
        good, bad, _ = expected_from_json(names[:2])
        assert count(spark, root, "bronze") == 40, (
            f"bronze should hold the 40 lines of day 1 and 2, got {count(spark, root, 'bronze')}")
        assert count(spark, root, "silver") == good, f"silver should hold {good} events, got {count(spark, root, 'silver')}"
        assert count(spark, root, "quarantine") == 0, "Nothing is broken on day 1 and 2"
        silver_history = history(spark, root, "silver")
        assert silver_history, "history() returned no versions: use DESCRIBE HISTORY on the table"
        silver_v1 = silver_history[-1][0]

        # Schema enforcement: the table refuses data that does not match
        silver_path = os.path.join(root, "silver")
        before = history(spark, root, "silver")
        try:
            (spark.createDataFrame([("x", "purchase", "u1", "pro", 12.5, None, "f")],
                                   "event_id string, kind string, user_id string, plan string, "
                                   "amount double, ts timestamp, file string")
             .write.format("delta").mode("append").save(silver_path))
            raise AssertionError("Appending user_id as a string should fail: is silver a Delta table "
                                 "with user_id BIGINT?")
        except AssertionError:
            raise
        except Exception as e:
            assert "DELTA_FAILED_TO_MERGE_FIELDS" in error_conditions(e), (
                f"Expected DELTA_FAILED_TO_MERGE_FIELDS for a string user_id, got {error_conditions(e)}")
        try:
            (spark.createDataFrame([("y", "purchase", 1, "pro", -5.0, None, "f")],
                                   "event_id string, kind string, user_id bigint, plan string, "
                                   "amount double, ts timestamp, file string")
             .write.format("delta").mode("append").save(silver_path))
            raise AssertionError("A negative amount should violate the positive_amount constraint")
        except AssertionError:
            raise
        except Exception as e:
            assert "DELTA_VIOLATE_CONSTRAINT_WITH_VALUES" in error_conditions(e), (
                f"Expected DELTA_VIOLATE_CONSTRAINT_WITH_VALUES, got {error_conditions(e)}")
        assert history(spark, root, "silver") == before, "A failed write must not add a version"

        # Day 3 arrives with drift, and day 2 is delivered a second time
        land_bronze(spark, root, [days[1], days[2]])
        refine(spark, root, with_country=True)
        refine(spark, root, with_country=True)  # a rerun must not add anything
        good, bad, revenue = expected_from_json(names)
        assert count(spark, root, "bronze") == 61, (
            f"bronze should hold 61 lines: day 2 again must not duplicate (MERGE on record_id); "
            f"got {count(spark, root, 'bronze')}")
        silver = spark.read.format("delta").load(silver_path)
        assert "country" in silver.columns, (
            "silver should have gained a country column: MERGE WITH SCHEMA EVOLUTION when "
            "with_country=True (without it, MERGE ... INSERT * silently drops the new column)")
        assert silver.count() == good, f"silver should hold {good} events (no duplicates), got {silver.count()}"
        assert silver.filter("amount IS NULL OR kind IS NULL OR user_id IS NULL").count() == 0, (
            "Every silver row needs kind, user_id and amount (day 3 amounts are objects: use "
            "get_json_object(amount, '$.value'))")
        countries = {r["file"]: r["n"] for r in
                     silver.filter("country IS NOT NULL").groupBy("file").agg(F.count("*").alias("n")).collect()}
        assert countries == {names[2]: 20}, f"Only the 20 day 3 events carry a country, got {countries}"
        q = spark.read.format("delta").load(os.path.join(root, "quarantine")).collect()
        assert len(q) == bad == 1 and q[0]["file"] == names[2] and q[0]["reason"] == "malformed", (
            f"quarantine should hold the truncated day 3 line with reason 'malformed', got {q}")
        assert q[0]["raw"].startswith('{"event_type": "purchase", "user": {"id": 9'), "Keep the raw line"

        gold = build_gold(spark, root)
        assert gold is not None, "build_gold() returned None"
        got = {str(r["day"]): (r["events"], r["revenue"]) for r in gold.collect()}
        want = {d: (20, v) for d, v in revenue.items()}
        assert got == want, f"gold should be {want}, got {got}"

        ops = [op for _, op in history(spark, root, "silver")]
        assert ops[:2] == ["CREATE TABLE", "ADD CONSTRAINT"] and ops.count("MERGE") >= 2, (
            f"silver history should start CREATE TABLE, ADD CONSTRAINT and contain the MERGEs; got {ops}")
        old = silver_as_of(spark, root, silver_v1)
        assert old is not None, "silver_as_of() returned None"
        assert old.count() == 40 and "country" not in old.columns, (
            f"Version {silver_v1} of silver (after day 1 and 2) should have 40 rows and no country "
            f"column; got {old.count()} rows, columns {old.columns}")

        print("Silver history:", history(spark, root, "silver"))
        print("Silver now:")
        silver.orderBy("ts").select("kind", "user_id", "plan", "country", "amount", "ts", "file").show(5)
        print("Quarantine:")
        spark.read.format("delta").load(os.path.join(root, "quarantine")).select("file", "reason", "raw").show(truncate=False)
        print("Gold:")
        gold.orderBy("day").show()
        print("All tests passed!")
    finally:
        spark.stop()
