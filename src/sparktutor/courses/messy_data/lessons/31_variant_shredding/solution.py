"""
VARIANT Shredding and Performance - Solution

Write the drifting events as VARIANT Parquet, read the Parquet footer to see
which fields Spark shredded into typed columns, then promote the stable fields
into a typed silver table and keep VARIANT for the rest.
"""

import glob
import os

import pyarrow.parquet as pq
from pyspark.sql import SparkSession, functions as sf

EVENTS = "data/messy/events"


def load_events(spark):
    """Read every events file as one VARIANT column `v`, one row per JSON line."""
    return spark.read.option("singleVariantColumn", "v").json(EVENTS)


def write_one_file(df, path):
    """Write `df` to `path` as Parquet in a single file; return that file's path."""
    df.coalesce(1).write.mode("overwrite").parquet(path)
    return glob.glob(os.path.join(path, "*.parquet"))[0]


def footer_columns(parquet_file):
    """Every leaf column path in the file's footer, such as 'v.typed_value.user.typed_value.id.typed_value'."""
    schema = pq.ParquetFile(parquet_file).schema
    return [schema.column(i).path for i in range(len(schema))]


def shredded_paths(columns):
    """Turn footer leaf paths into the VARIANT fields that got a typed column.

    'v.typed_value.user.typed_value.id.typed_value' -> 'user.id'
    'v.typed_value.items.typed_value.list.element.typed_value.sku.typed_value' -> 'items[].sku'
    Columns that do not end in 'typed_value' (the binary fallbacks) are skipped.
    """
    paths = set()
    for column in columns:
        parts = column.split(".")
        if parts[-1] != "typed_value":
            continue
        names = []
        for part in parts[1:-1]:  # drop the column name and the final typed_value
            if part in ("typed_value", "list"):
                continue
            if part == "element":
                names[-1] += "[]"
            else:
                names.append(part)
        if names:
            paths.add(".".join(names))
    return paths


def plan_counts(df):
    """Rows per user plan (NULL where there is no plan), read with a typed extraction."""
    plan = sf.try_variant_get("v", "$.user.plan", "string").alias("plan")
    return df.groupBy(plan).count()


def silver_events(df):
    """Promote the stable, frequently used fields to typed columns; keep the payload as VARIANT."""
    v = sf.col("v")
    return (df.filter(v.isNotNull())
        .select(
            sf.coalesce(sf.try_variant_get(v, "$.event", "string"),
                        sf.try_variant_get(v, "$.event_type", "string")).alias("event"),
            sf.coalesce(sf.try_variant_get(v, "$.user_id", "int"),
                        sf.try_variant_get(v, "$.user.id", "int")).alias("user_id"),
            sf.coalesce(sf.try_variant_get(v, "$.amount", "double"),
                        sf.try_variant_get(v, "$.amount.value", "double")).alias("amount"),
            sf.to_timestamp(sf.try_variant_get(v, "$.ts", "string")).alias("ts"),
            v.alias("payload"),
        ))


# ---- Test harness ----
if __name__ == "__main__":
    import contextlib
    import io
    import json
    import tempfile

    spark = (SparkSession.builder
        .appName("VariantShredding")
        .master("local[*]")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    # Expected values, computed from the files with plain Python
    lines, amounts = 0, []
    for name in sorted(os.listdir(EVENTS)):
        for line in open(os.path.join(EVENTS, name)):
            lines += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            a = rec["amount"]
            amounts.append(float(a["value"] if isinstance(a, dict) else a))

    def read_schema(df):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            df.explain()
        return [l.split("ReadSchema: ")[1] for l in buf.getvalue().splitlines() if "ReadSchema: " in l]

    out = tempfile.mkdtemp(prefix="shred_")
    try:
        events = load_events(spark)
        assert events is not None, "load_events returned None"
        assert events.columns == ["v"], (
            f"Expected one column named v, got {events.columns}: use option('singleVariantColumn', 'v')")
        assert dict(events.dtypes)["v"] == "variant", f"v should be a VARIANT column, got {events.dtypes}"
        assert events.count() == lines, f"Expected one row per line ({lines}), got {events.count()}"

        # 1. All three days in one file: shredding is decided per file
        all_file = write_one_file(events, os.path.join(out, "all"))
        assert all_file and all_file.endswith(".parquet"), (
            f"write_one_file should return the path of the .parquet file it wrote, got {all_file}")
        all_cols = footer_columns(all_file)
        paths = shredded_paths(all_cols)
        assert paths, "shredded_paths returned nothing: keep the columns that end in 'typed_value'"
        for p in ["event", "event_type", "user.id", "user.plan", "user.geo.country", "items[].sku", "items[].qty"]:
            assert p in paths, f"{p} should be shredded in the three-day file; your paths: {sorted(paths)}"
        assert "amount" not in paths, (
            "amount is a number, a string or an object depending on the day, so it has no "
            f"typed_value in the three-day file; your paths: {sorted(paths)}")
        assert "user" not in paths and "items" not in paths and "items[]" not in paths, (
            f"Only leaf fields belong in the set (user.id, not user); got {sorted(paths)}")

        # 2. Day one alone: amount is always a decimal there, so it does get a typed column
        day1 = events.filter(sf.col("_metadata.file_name").contains("10-01"))
        day1_paths = shredded_paths(footer_columns(write_one_file(day1, os.path.join(out, "day1"))))
        assert "amount" in day1_paths, f"In the day-one file amount should be shredded; got {sorted(day1_paths)}"

        # 3. Shredding switched off: only metadata and value remain
        spark.conf.set("spark.sql.variant.writeShredding.enabled", "false")
        try:
            plain_cols = footer_columns(write_one_file(events, os.path.join(out, "plain")))
        finally:
            spark.conf.unset("spark.sql.variant.writeShredding.enabled")
        assert shredded_paths(plain_cols) == set(), f"With shredding off nothing is shredded, got {plain_cols}"
        assert sorted(plain_cols) == ["v.metadata", "v.value"], f"Unexpected unshredded layout {plain_cols}"

        # 4. A typed extraction asks the scan for just one typed field
        stored = spark.read.parquet(os.path.join(out, "all"))
        counts = plan_counts(stored)
        assert counts is not None, "plan_counts returned None"
        got = {r[0]: r["count"] for r in counts.collect()}
        assert got == {None: 21, "free": 9, "pro": 31}, (
            f"Expected 21 rows without a plan, 9 free and 31 pro, got {got}")
        schemas = read_schema(counts)
        assert schemas and "0:string" in schemas[0], (
            f"The scan should read the plan as a string field, got ReadSchema {schemas}. "
            "Use try_variant_get(v, '$.user.plan', 'string'), not v:user.plan::string")

        # 5. Silver: typed columns for the stable fields, VARIANT for the rest
        silver = silver_events(stored)
        assert silver is not None, "silver_events returned None"
        types = dict(silver.dtypes)
        expected_types = {"event": "string", "user_id": "int", "amount": "double",
                          "ts": "timestamp", "payload": "variant"}
        assert types == expected_types, f"Expected columns and types {expected_types}, got {types}"
        rows = silver.collect()
        assert len(rows) == len(amounts), (
            f"Expected {len(amounts)} rows (the malformed line has a NULL v; drop it), got {len(rows)}")
        for c in ["event", "user_id", "amount", "ts"]:
            missing = sum(1 for r in rows if r[c] is None)
            assert missing == 0, f"{missing} rows have a NULL {c}: coalesce over every shape the field takes"
        total = round(sum(r["amount"] for r in rows), 2)
        assert total == round(sum(amounts), 2), f"Amounts should sum to {round(sum(amounts), 2)}, got {total}"

        print("Shredded in the three-day file:", sorted(paths))
        print("Shredded in the day-one file:  ", sorted(day1_paths))
        print("Plan scan:", schemas[0])
        silver.groupBy("event").agg(sf.count("*").alias("n"), sf.round(sf.sum("amount"), 2).alias("amount")) \
            .orderBy("event").show()
        print("All tests passed!")
    finally:
        spark.stop()
