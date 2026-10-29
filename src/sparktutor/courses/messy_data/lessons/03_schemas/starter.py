"""
Schemas for Data You Don't Control - Starter Code

A schema contract for the sample order events: store it in a file, load
it back, compare what really arrives with it (drift), read files through
it, and align a DataFrame with a different shape to it so it can be
combined with others.
"""

import json

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import ArrayType, MapType, StructType

# The contract the team agreed on for order events
CONTRACT_DDL = """
    event STRING,
    user STRUCT<id: BIGINT, plan: STRING>,
    amount DOUBLE,
    items ARRAY<STRUCT<qty: BIGINT, sku: STRING>>,
    ts TIMESTAMP
"""


def save_contract(schema, path):
    """Write `schema` (a StructType) to `path` as JSON."""
    # TODO 1: write schema.json() to the file at path
    pass


def load_contract(path):
    """Read a StructType back from a JSON file written by save_contract."""
    # TODO 2: json.load the file and rebuild the schema with StructType.fromJson
    return None


def schema_drift(expected, actual, prefix=""):
    """Differences between two StructTypes, ignoring nullability.

    Returns a sorted list of (kind, path, detail) tuples:
      ("missing", path, expected type)       in expected, not in actual
      ("added", path, actual type)           in actual, not in expected
      ("type_changed", path, "old -> new")   in both, with different types
    Nested struct fields use dots ("user.geo"). When both sides are structs
    the comparison goes inside them instead of reporting the whole struct.
    Types are compared with simpleString(), which leaves out nullability.
    """
    drift = []
    actual_fields = {f.name: f for f in actual.fields}
    expected_names = {f.name for f in expected.fields}
    # TODO 3: for each field of expected (path = prefix + field.name):
    #   - not in actual_fields: append ("missing", path, field.dataType.simpleString())
    #   - both types are StructType: drift.extend(schema_drift(e, a, path + "."))
    #   - simpleString() differs: append ("type_changed", path, "<expected> -> <actual>")
    #   then for each field of actual whose name is not in expected_names:
    #   append ("added", prefix + name, its simpleString())
    #   Return the list sorted.
    return None


def load_with_contract(spark, path, contract_path):
    """Read the JSON files at `path` through the stored contract.

    Returns (df, drift):
      df:    the contract's columns, in the contract's order, plus `_file`
             (the source file name from the hidden _metadata column)
      drift: schema_drift(contract, the schema Spark infers for the files,
             with timestamp inference on)
    """
    # TODO 4: load the contract; infer the files' schema with
    #   spark.read.option("inferTimestamp", True).json(path).schema;
    #   compute the drift; read the files with spark.read.schema(contract)
    #   and add _file from F.col("_metadata.file_name"); return (df, drift)
    return None


def is_atomic(data_type):
    """True for plain types (numbers, strings, dates...), False for struct, array and map."""
    return not isinstance(data_type, (StructType, ArrayType, MapType))


def align_column(col, actual, expected):
    """An expression that turns `col` (of type `actual`) into type `expected`.

    - same type: keep the column
    - both structs: build the expected struct field by field (recursively);
      fields the actual struct lacks become NULL
    - both plain types: try_cast (bad values become NULL instead of failing)
    - anything else (a struct where a number was expected...): NULL
    """
    if actual.simpleString() == expected.simpleString():
        return col
    if isinstance(actual, StructType) and isinstance(expected, StructType):
        have = {f.name: f.dataType for f in actual.fields}
        parts = []
        for f in expected.fields:
            if f.name in have:
                parts.append(align_column(col.getField(f.name), have[f.name], f.dataType).alias(f.name))
            else:
                parts.append(F.lit(None).cast(f.dataType).alias(f.name))
        return F.when(col.isNull(), F.lit(None)).otherwise(F.struct(*parts)).cast(expected)
    # TODO 5a: when both types are plain (is_atomic), return col.try_cast(expected);
    #   otherwise return a NULL of the expected type: F.lit(None).cast(expected)
    return col  # placeholder: keeps the column unchanged, so the schema check fails


def align_to(df, contract):
    """`df` reshaped to exactly the contract's columns, names, order and types.

    Columns the contract doesn't list are dropped; columns it lists that `df`
    lacks are added as NULL of the right type.
    """
    have = {f.name: f.dataType for f in df.schema.fields}
    # TODO 5b: for each field of the contract, in order: if df has it, use
    #   align_column(F.col(name), have[name], field.dataType); if not, a NULL
    #   cast to field.dataType. Alias each to the field's name and select them.
    return None


# ---- Test harness ----
if __name__ == "__main__":
    import os
    import shutil
    import tempfile

    spark = (SparkSession.builder
             .appName("Schemas")
             .master("local[4]")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    tmp = tempfile.mkdtemp()
    DAY1 = "data/messy/events/events_2026-10-01.json"
    DAY3 = "data/messy/events/events_2026-10-03.json"

    try:
        contract = StructType.fromDDL(CONTRACT_DDL)
        contract_path = os.path.join(tmp, "events_contract.json")

        # 1. Store and reload the contract
        save_contract(contract, contract_path)
        assert os.path.exists(contract_path), "save_contract did not create the file"
        with open(contract_path) as f:
            assert json.load(f)["type"] == "struct", "The file should hold schema.json(), a JSON object with type 'struct'"
        loaded = load_contract(contract_path)
        assert loaded == contract, f"load_contract should give back the same schema, got {loaded}"

        # 2. Drift of each day against the contract
        def observed(p):
            return spark.read.option("inferTimestamp", True).json(p).schema

        d1 = schema_drift(contract, observed(DAY1))
        assert d1 is not None, "schema_drift returned None: complete TODO 3"
        expected_d1 = [("added", "user_id", "bigint"),
                       ("missing", "items", "array<struct<qty:bigint,sku:string>>"),
                       ("missing", "user", "struct<id:bigint,plan:string>")]
        assert d1 == expected_d1, f"Day 1 drift should be\n  {expected_d1}\ngot\n  {d1}"

        d3 = schema_drift(contract, observed(DAY3))
        expected_d3 = [("added", "_corrupt_record", "string"),
                       ("added", "event_type", "string"),
                       ("added", "user.geo", "struct<country:string>"),
                       ("missing", "event", "string"),
                       ("type_changed", "amount", "double -> struct<currency:string,value:double>")]
        assert d3 == expected_d3, (
            f"Day 3 drift should be\n  {expected_d3}\ngot\n  {d3}\n"
            "Go inside structs that exist on both sides (user), compare types with simpleString(), "
            "and sort the result")

        # 3. Reading every day through the contract
        result = load_with_contract(spark, "data/messy/events", contract_path)
        assert result is not None, "load_with_contract returned None: complete TODO 4"
        df, drift = result
        expected_cols = [f.name for f in contract.fields] + ["_file"]
        assert df.columns == expected_cols, f"Columns should be {expected_cols}, got {df.columns}"
        assert df.schema["ts"].dataType.simpleString() == "timestamp", "ts should be a timestamp, as in the contract"
        rows = df.collect()
        assert len(rows) == 61, f"Expected 61 rows (20 + 20 + 21 lines), got {len(rows)}"
        per_file = {}
        for r in rows:
            per_file.setdefault(r["_file"], []).append(r)
        assert sorted(per_file) == ["events_2026-10-01.json", "events_2026-10-02.json", "events_2026-10-03.json"], (
            f"_file should hold the file name from _metadata.file_name, got {sorted(per_file)}")
        amounts = {k: sum(r["amount"] is not None for r in v) for k, v in per_file.items()}
        assert amounts == {"events_2026-10-01.json": 20, "events_2026-10-02.json": 15, "events_2026-10-03.json": 0}, (
            f"Amounts read as DOUBLE per file should be 20, 15 and 0 (string and object amounts don't fit); got {amounts}")
        kinds = {k for k, _, _ in drift}
        assert ("type_changed", "amount", "double -> string") in drift and kinds == {"added", "type_changed"}, (
            f"Over all three days, amount infers as string, and event and user exist in some file; got {drift}")

        # 4. Aligning an inferred DataFrame to the contract, then combining days
        day3 = spark.read.option("inferTimestamp", True).json(DAY3)
        aligned3 = align_to(day3, contract)
        assert aligned3 is not None, "align_to returned None: complete TODO 5"
        assert aligned3.schema.simpleString() == contract.simpleString(), (
            f"align_to must produce exactly the contract schema\n  {contract.simpleString()}\ngot\n  "
            f"{aligned3.schema.simpleString()}")
        r3 = aligned3.collect()
        assert sum(r["user"] is not None and r["user"]["id"] is not None for r in r3) == 20, (
            "user.id exists on day 3 (with an extra geo field): keep it by rebuilding the struct field by field")
        assert all(r["amount"] is None for r in r3), "Day 3's amount is an object; it can't become a DOUBLE, so it is NULL"
        assert all(r["event"] is None for r in r3), "Day 3 has no event column; it should be added as NULL"
        assert sum(r["items"] is not None for r in r3) == 20, "items has the same type on day 3 and should be kept as it is"

        day1 = spark.read.option("inferTimestamp", True).json(DAY1)
        both = align_to(day1, contract).unionByName(aligned3)
        assert both.count() == 41, f"Day 1 (20 rows) plus day 3 (21 rows) should give 41, got {both.count()}"

        print("Contract:", contract.simpleString())
        print("Day 1 drift:", d1)
        print("Day 3 drift:")
        for d in d3:
            print("  ", d)
        print("Read through the contract, amounts that fit DOUBLE per file:", amounts)
        df.groupBy("_file").agg(F.count("*").alias("rows"), F.count("event").alias("event"),
                                F.count("user").alias("user"), F.count("amount").alias("amount")).orderBy("_file").show()
        print("Day 3 aligned to the contract:")
        aligned3.show(3, truncate=False)
        print("All tests passed!")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        spark.stop()
