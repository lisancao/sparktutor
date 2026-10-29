# spark-connectors: delta
"""
Production Ingestion: Quality Rules, Quarantine and Pipelines - Solution

Land daily order files into Delta tables with quality rules as data:

  bronze/      every row as received (strings), replaced per source file
  quarantine/  rows that broke an error rule, with failed_rules, per file
  silver/      typed, valid, deduplicated orders (MERGE on order_id),
               guarded by CHECK constraints and a quality gate

A day whose error ratio is above the threshold raises QualityGateError
after bronze and quarantine are written and before silver is touched.
"""

import json
import os
import tempfile

from pyspark.sql import DataFrame, Observation, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

QUALITY = "data/messy/quality"
ORDER_COLUMNS = ["order_id", "customer_id", "order_ts", "quantity", "unit_price", "status", "currency"]


class QualityGateError(Exception):
    """Raised when a file has too many bad rows to publish."""


def profile(df: DataFrame) -> DataFrame:
    """One row per column of df, computed in a single aggregation:

    column, rows, missing (NULL or blank after trim), distinct
    (approx_count_distinct with rsd 0.01) and top (the most frequent
    non-NULL value, as a string, lowest value on ties).
    """
    aggs = [F.count(F.lit(1)).alias("rows")]
    for c in df.columns:
        aggs += [
            F.count_if(F.col(c).isNull() | (F.trim(F.col(c).cast("string")) == "")).alias(f"{c}__missing"),
            F.approx_count_distinct(c, 0.01).alias(f"{c}__distinct"),
            F.mode(c, True).cast("string").alias(f"{c}__top"),
        ]
    one_row = df.agg(*aggs)
    return one_row.select(F.inline(F.array(*[
        F.struct(F.lit(c).alias("column"), F.col("rows"),
                 F.col(f"{c}__missing").alias("missing"),
                 F.col(f"{c}__distinct").alias("distinct"),
                 F.col(f"{c}__top").alias("top"))
        for c in df.columns])))


def apply_rules(df: DataFrame, rules: list) -> DataFrame:
    """Add failed_rules (names of the broken 'error' rules) and warnings
    (names of the broken 'warn' rules), both array<string>, in one pass.

    A check that evaluates to NULL counts as broken.
    """
    def names(severity):
        return F.array_compact(F.array(*[
            F.when(~F.coalesce(F.expr(r["check"]), F.lit(False)), F.lit(r["name"]))
            for r in rules if r["severity"] == severity]))
    return df.withColumn("failed_rules", names("error")).withColumn("warnings", names("warn"))


def dataset_checks(customers: DataFrame, orders: DataFrame) -> dict:
    """Checks that need more than one row at a time.

    duplicate_keys: sorted customer_ids that appear more than once
    orphan_orders:  sorted order_ids whose customer_id is not blank but is
                    not a known customer (a left anti join)
    """
    dups = (customers.groupBy("customer_id").count().where("count > 1")
            .orderBy("customer_id").collect())
    orphans = (orders.where("trim(customer_id) <> ''")
               .join(customers.select("customer_id"), "customer_id", "left_anti")
               .orderBy("order_id").collect())
    return {"duplicate_keys": [r["customer_id"] for r in dups],
            "orphan_orders": [r["order_id"] for r in orphans]}


def create_tables(spark: SparkSession, root: str) -> None:
    """Create the silver table once, with CHECK constraints (given)."""
    silver = f"delta.`{root}/silver`"
    spark.sql(f"""CREATE TABLE IF NOT EXISTS {silver} (
        order_id STRING, customer_id STRING, order_ts TIMESTAMP, quantity INT,
        unit_price DECIMAL(10,2), status STRING, currency STRING,
        warnings ARRAY<STRING>, _source_file STRING) USING delta""")
    existing = spark.sql(f"SHOW TBLPROPERTIES {silver}").collect()
    if not any(r["key"].startswith("delta.constraints.") for r in existing):
        spark.sql(f"ALTER TABLE {silver} ADD CONSTRAINT quantity_positive CHECK (quantity > 0)")
        spark.sql(f"ALTER TABLE {silver} ADD CONSTRAINT price_not_negative CHECK (unit_price >= 0)")


def land_day(spark: SparkSession, csv_path: str, root: str, rules: list,
             customers: DataFrame, max_error_ratio: float) -> dict:
    """Land one order file. Safe to run again for the same file.

    1. bronze: the raw rows plus _source_file, _file_date and _ingested_at,
       written with replaceWhere on _source_file
    2. apply the rules (after adding _customer_known), observing rows,
       quarantined and warned with an Observation while writing the
       quarantine (replaceWhere on _source_file)
    3. gate: raise QualityGateError if quarantined / rows > max_error_ratio
    4. silver: valid rows, typed, one per order_id, MERGE ... WHEN NOT
       MATCHED THEN INSERT, with file, rows, quarantined and warned as the
       commit's userMetadata
    Returns {"file", "rows", "quarantined", "warned", "inserted"}.
    """
    file_name = os.path.basename(csv_path)
    only_this_file = f"_source_file = '{file_name}'"

    raw = (spark.read.option("header", True).schema(", ".join(f"{c} STRING" for c in ORDER_COLUMNS))
           .csv(csv_path)
           .withColumn("_source_file", F.col("_metadata.file_name"))
           .withColumn("_file_date", F.to_date(F.regexp_extract("_source_file", r"(\d{4}-\d{2}-\d{2})", 1)))
           .withColumn("_ingested_at", F.current_timestamp()))
    (raw.write.format("delta").mode("overwrite")
     .option("replaceWhere", only_this_file).save(f"{root}/bronze"))

    assert os.path.isdir(f"{root}/bronze/_delta_log"), "bronze was not written as a Delta table (step 1)"
    bronze = spark.read.format("delta").load(f"{root}/bronze").where(only_this_file)
    known = customers.select("customer_id").distinct().withColumn("_customer_known", F.lit(True))
    checked = apply_rules(
        bronze.join(known, "customer_id", "left")
              .withColumn("_customer_known", F.coalesce("_customer_known", F.lit(False))),
        rules).persist()

    stats = Observation(f"quality_{file_name}")
    (checked.observe(stats,
                     F.count(F.lit(1)).alias("rows"),
                     F.count_if(F.size("failed_rules") > 0).alias("quarantined"),
                     F.count_if(F.size("warnings") > 0).alias("warned"))
     .where(F.size("failed_rules") > 0)
     .select(*ORDER_COLUMNS, "failed_rules", "_source_file", "_ingested_at")
     .write.format("delta").mode("overwrite").option("replaceWhere", only_this_file)
     .save(f"{root}/quarantine"))
    m = stats.get
    result = {"file": file_name, "rows": m["rows"], "quarantined": m["quarantined"],
              "warned": m["warned"], "inserted": 0}

    ratio = m["quarantined"] / m["rows"] if m["rows"] else 1.0
    if ratio > max_error_ratio:
        checked.unpersist()
        raise QualityGateError(
            f"{file_name}: {m['quarantined']} of {m['rows']} rows ({ratio:.0%}) broke a rule; "
            f"the limit is {max_error_ratio:.0%}. Silver was not changed; see the quarantine.")

    first = Window.partitionBy("order_id").orderBy("order_ts")
    valid = (checked.where(F.size("failed_rules") == 0)
             .withColumn("_rn", F.row_number().over(first)).where("_rn = 1")
             .select("order_id", "customer_id",
                     F.try_to_timestamp("order_ts").alias("order_ts"),
                     F.col("quantity").cast("int").alias("quantity"),
                     F.col("unit_price").cast("decimal(10,2)").alias("unit_price"),
                     F.lower(F.trim("status")).alias("status"),
                     "currency", "warnings", "_source_file"))
    valid.createOrReplaceTempView("incoming_orders")
    # The counts go into the commit itself, so DESCRIBE HISTORY shows them.
    metadata = {k: result[k] for k in ("file", "rows", "quarantined", "warned")}
    spark.conf.set("spark.databricks.delta.commitInfo.userMetadata", json.dumps(metadata))
    try:
        merged = spark.sql(f"""
            MERGE INTO delta.`{root}/silver` AS t
            USING incoming_orders AS s
            ON t.order_id = s.order_id
            WHEN NOT MATCHED THEN INSERT *""").collect()[0]
    finally:
        spark.conf.unset("spark.databricks.delta.commitInfo.userMetadata")
        checked.unpersist()
    result["inserted"] = merged["num_inserted_rows"]
    return result


# ---------------------------------------------------------------- harness
def silver_version(spark, root):
    return spark.sql(f"DESCRIBE HISTORY delta.`{root}/silver`").agg(F.max("version")).first()[0]


if __name__ == "__main__":
    spark = (SparkSession.builder.master("local[2]")
             .appName("ProductionIngestion")
             .config("spark.sql.shuffle.partitions", "2")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    rules = json.load(open(f"{QUALITY}/rules.json"))
    customers = spark.read.option("header", True).csv(f"{QUALITY}/customers.csv")

    # --- 1. profile ---
    prof = profile(customers)
    assert isinstance(prof, DataFrame), "profile must return a DataFrame"
    prof.show(truncate=False)
    by_col = {r["column"]: r for r in prof.collect()}
    assert set(by_col) == set(customers.columns), f"profile needs one row per column, got {sorted(by_col)}"
    assert by_col["email"]["missing"] == 1 and by_col["country"]["missing"] == 1, \
        "email and country each have one missing (NULL or blank) value"
    assert by_col["customer_id"]["rows"] == 41, "rows should be the number of rows in the file (41)"
    assert abs(by_col["customer_id"]["distinct"] - 40) <= 1, \
        f"about 40 distinct customer_ids expected, got {by_col['customer_id']['distinct']} (use rsd 0.01)"
    assert by_col["customer_id"]["top"] == "C017", "the most frequent customer_id is the duplicated C017"
    assert by_col["country"]["top"] == "US", "the most frequent country is US"
    print("profile: OK")

    # --- 2. rules ---
    day1 = spark.read.option("header", True).csv(f"{QUALITY}/orders/orders_2026-10-01.csv") \
        .withColumn("_file_date", F.lit("2026-10-01").cast("date")) \
        .join(customers.select("customer_id").distinct().withColumn("_customer_known", F.lit(True)),
              "customer_id", "left") \
        .withColumn("_customer_known", F.coalesce("_customer_known", F.lit(False)))
    ruled = apply_rules(day1, rules)
    assert isinstance(ruled, DataFrame), "apply_rules must return a DataFrame"
    assert {"failed_rules", "warnings"} <= set(ruled.columns), "apply_rules must add failed_rules and warnings"
    rows = {r["order_id"]: r for r in ruled.collect()}
    assert sum(1 for r in rows.values() if r["failed_rules"]) == 6, "day 1 has 6 rows that break an error rule"
    assert sorted(rows["O0041"]["failed_rules"]) == ["quantity_is_integer", "quantity_positive"], \
        "a blank quantity breaks quantity_is_integer and quantity_positive (a NULL check counts as broken)"
    assert rows["O0032"]["failed_rules"] == [] and rows["O0032"]["warnings"] == ["status_lowercase"], \
        "SHIPPED is only a warning: it is a valid status in the wrong case"
    print("apply_rules: OK")

    # --- 3. dataset checks ---
    orders = spark.read.option("header", True).csv(f"{QUALITY}/orders")
    checks = dataset_checks(customers, orders)
    print("dataset checks:", checks)
    assert checks == {"duplicate_keys": ["C017"], "orphan_orders": ["O0012", "O0063"]}, \
        "expected C017 as the only duplicate key and O0012, O0063 as orphan orders"

    # --- 4. land the days ---
    root = tempfile.mkdtemp()
    create_tables(spark, root)
    r1 = land_day(spark, f"{QUALITY}/orders/orders_2026-10-01.csv", root, rules, customers, 0.2)
    assert isinstance(r1, dict), "land_day must return a dict"
    print(r1)
    assert (r1["rows"], r1["quarantined"], r1["warned"], r1["inserted"]) == (60, 6, 1, 54), \
        "day 1: 60 rows, 6 quarantined, 1 warned, 54 inserted into silver"
    r2 = land_day(spark, f"{QUALITY}/orders/orders_2026-10-02.csv", root, rules, customers, 0.2)
    print(r2)
    assert (r2["rows"], r2["quarantined"], r2["inserted"]) == (60, 8, 49), \
        "day 2: 60 rows, 8 quarantined, 49 new orders (O0006 and O0007 were re-sent, O0073 is listed twice)"
    v2 = silver_version(spark, root)
    again = land_day(spark, f"{QUALITY}/orders/orders_2026-10-02.csv", root, rules, customers, 0.2)
    print("day 2 again:", again)
    assert again["inserted"] == 0, "landing the same file twice must not insert anything"
    assert silver_version(spark, root) == v2, "a MERGE that inserts nothing should not create a silver version"
    count = lambda name: spark.read.format("delta").load(f"{root}/{name}").count()
    assert count("bronze") == 120, f"bronze should hold 120 rows after a re-run, got {count('bronze')} (use replaceWhere)"
    assert count("quarantine") == 14, f"quarantine should hold 14 rows after a re-run, got {count('quarantine')}"
    assert count("silver") == 103, f"silver should hold 103 orders, got {count('silver')}"

    # --- 5. the broken day ---
    before = silver_version(spark, root)
    try:
        land_day(spark, f"{QUALITY}/incoming/orders_2026-10-03.csv", root, rules, customers, 0.2)
        raise AssertionError("day 3 is 75% bad: land_day should raise QualityGateError")
    except QualityGateError as e:
        print("gate:", e)
    assert silver_version(spark, root) == before, "the gate must stop day 3 before any silver commit"
    assert count("silver") == 103 and count("bronze") == 180 and count("quarantine") == 59, \
        "after day 3: silver unchanged (103), bronze and quarantine keep the evidence (180 and 59 rows)"

    # --- 6. history and constraints ---
    history = spark.sql(f"DESCRIBE HISTORY delta.`{root}/silver`").orderBy("version")
    history.select("version", "operation", "userMetadata").show(truncate=False)
    merges = [json.loads(r["userMetadata"]) for r in history.collect() if r["operation"] == "MERGE"]
    assert [(m["file"], m["quarantined"]) for m in merges] == [("orders_2026-10-01.csv", 6), ("orders_2026-10-02.csv", 8)], \
        "each MERGE that changed silver should record its file and counts in userMetadata"
    try:
        spark.sql(f"INSERT INTO delta.`{root}/silver` (order_id, quantity) VALUES ('BAD', 0)")
        raise AssertionError("the quantity_positive constraint should reject quantity 0")
    except AssertionError:
        raise
    except Exception as e:
        assert "DELTA_VIOLATE_CONSTRAINT_WITH_VALUES" in str(e), f"unexpected error: {str(e)[:200]}"
        print("constraint: rejected quantity 0")

    print("All tests passed!")
    spark.stop()
