"""
Production Ingestion, part 2: The Quality Pipeline - Solution

The orders ingestion from part 1 as a Declarative Pipeline. Open source
Spark 4.2.0 has no expectation decorators, so quality is built from
datasets:

    bronze_orders      streaming table: every CSV row as text, with lineage
    customers_dim      materialized view: one row per customer_id
    orders_checked     temporary view: failed_rules and warnings per row
    quality_report     materialized view: one row per file, with ratios
    quality_gate       temporary view: fails the run if any file is too bad
    silver_orders      materialized view: typed, valid, deduplicated orders,
                       computed *through* quality_gate so it cannot be
                       refreshed from a bad file
    quarantine_orders  materialized view: rows that broke a rule, with the
                       names of the rules
    check_*            assert_true checks (graded)
"""

import json

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

spark: SparkSession

QUALITY = "data/messy/quality"
RULES = json.load(open(f"{QUALITY}/rules.json"))
MAX_ERROR_RATIO = 0.2
ORDER_SCHEMA = ("order_id STRING, customer_id STRING, order_ts STRING, quantity STRING, "
                "unit_price STRING, status STRING, currency STRING")


def failed(severity: str):
    """Names of the rules of this severity that a row breaks.

    A check that is NULL (for example `try_cast(quantity AS INT) > 0` on a
    blank quantity) counts as broken: coalesce(check, false).
    """
    names = [F.when(~F.coalesce(F.expr(r["check"]), F.lit(False)), F.lit(r["name"]))
             for r in RULES if r["severity"] == severity]
    return F.array_compact(F.array(*names))


# ---- Bronze ----
@dp.table(comment="Every order row as received, all columns as text")
def bronze_orders() -> DataFrame:
    return (spark.readStream.option("header", True).schema(ORDER_SCHEMA)
            .csv(f"{QUALITY}/orders")
            .withColumn("_source_file", F.col("_metadata.file_name"))
            .withColumn("_file_date", F.to_date(F.regexp_extract(
                "_source_file", r"(\d{4}-\d{2}-\d{2})", 1)))
            .withColumn("_ingested_at", F.current_timestamp()))


@dp.materialized_view(comment="One row per customer: the first one listed wins")
def customers_dim() -> DataFrame:
    first = Window.partitionBy("customer_id").orderBy(F.col("_row"))
    return (spark.read.option("header", True).csv(f"{QUALITY}/customers.csv")
            .withColumn("_row", F.monotonically_increasing_id())
            .withColumn("_rn", F.row_number().over(first))
            .where("_rn = 1")
            .select("customer_id", "name", "email", "country"))


# ---- Rules ----
@dp.temporary_view
def orders_checked() -> DataFrame:
    known = spark.read.table("customers_dim").select(
        "customer_id", F.lit(True).alias("_in_dim"))
    # select, not withColumn: on 4.2.0, withColumn over a pipeline dataset
    # loses the dependency edge once the upstream table exists, and a
    # second run then reads stale data (SPARK-59663).
    return (spark.read.table("bronze_orders")
            .join(known, "customer_id", "left")
            .select("*", F.coalesce("_in_dim", F.lit(False)).alias("_customer_known"))
            .select("*", failed("error").alias("failed_rules"), failed("warn").alias("warnings")))


@dp.materialized_view(comment="Quality per input file")
def quality_report() -> DataFrame:
    return (spark.read.table("orders_checked")
            .groupBy("_source_file")
            .agg(F.count("*").alias("rows"),
                 F.count_if(F.size("failed_rules") > 0).alias("quarantined"),
                 F.count_if(F.size("warnings") > 0).alias("warned"))
            .select("*", F.round(F.col("quarantined") / F.col("rows"), 4).alias("error_ratio")))


@dp.temporary_view
def quality_gate() -> DataFrame:
    report = spark.read.table("quality_report")
    return report.agg(
        F.assert_true(F.max("error_ratio") <= MAX_ERROR_RATIO,
                      f"quality gate: a file has more than {MAX_ERROR_RATIO:.0%} bad rows; "
                      "see quality_report").alias("_gate"))


# ---- Silver and quarantine ----
@dp.materialized_view(comment="Valid orders, typed, one row per order_id")
def silver_orders() -> DataFrame:
    first_seen = Window.partitionBy("order_id").orderBy("_file_date", "_ingested_at")
    return (spark.read.table("orders_checked")
            # The filter on _gate is what enforces the gate: a column nobody
            # uses is pruned by the optimizer, and its assert_true never runs.
            .crossJoin(spark.read.table("quality_gate"))
            .where(F.col("_gate").isNull())
            .where(F.size("failed_rules") == 0)
            .select("*", F.row_number().over(first_seen).alias("_rn"))
            .where("_rn = 1")
            .select("order_id", "customer_id",
                    F.try_to_timestamp("order_ts").alias("order_ts"),
                    F.col("quantity").cast("int").alias("quantity"),
                    F.col("unit_price").cast("decimal(10,2)").alias("unit_price"),
                    F.lower(F.trim("status")).alias("status"),
                    "currency", "warnings", "_source_file"))


@dp.materialized_view(comment="Rows that broke at least one rule, with the rule names")
def quarantine_orders() -> DataFrame:
    return (spark.read.table("orders_checked")
            .where(F.size("failed_rules") > 0)
            .select("order_id", "customer_id", "order_ts", "quantity", "unit_price",
                    "status", "currency", "failed_rules", "_source_file"))


# ---- Checks (do not modify below this line) ----
def _expect(table: str, condition: str, message: str) -> DataFrame:
    return spark.read.table(table).agg(F.expr(condition).alias("ok")).select(
        F.assert_true(F.col("ok"), f"{table}: {message}").alias("ok"))


@dp.materialized_view
def check_bronze() -> DataFrame:
    return _expect("bronze_orders", "count(*) = 120 AND count(DISTINCT _source_file) = 2",
                   "expected all 120 rows of the two order files, as received")


@dp.materialized_view
def check_quarantine() -> DataFrame:
    return _expect(
        "quarantine_orders",
        "count(*) = 14 "
        "AND count_if(array_contains(failed_rules, 'customer_known')) = 4 "
        "AND count_if(array_contains(failed_rules, 'quantity_positive')) = 4 "
        "AND count_if(array_contains(failed_rules, 'unit_price_is_number')) = 3 "
        "AND count_if(array_contains(failed_rules, 'order_ts_not_after_file_day')) = 1",
        "expected 14 quarantined rows: 4 unknown or blank customers, 4 bad quantities, "
        "3 bad prices, 1 order dated after its file's day (and more)")


@dp.materialized_view
def check_silver() -> DataFrame:
    return _expect(
        "silver_orders",
        "count(*) = 103 AND count(DISTINCT order_id) = 103 "
        "AND typeof(max(unit_price)) = 'decimal(10,2)' "
        "AND count_if(status = 'shipped' AND array_contains(warnings, 'status_lowercase')) = 1",
        "expected 103 unique valid orders with decimal prices, and the SHIPPED row kept "
        "(normalized) with a status_lowercase warning")


@dp.materialized_view
def check_report() -> DataFrame:
    return _expect(
        "quality_report",
        "count(*) = 2 AND sum(rows) = 120 AND sum(quarantined) = 14 AND max(error_ratio) <= 0.2",
        "expected one report row per file, 120 rows and 14 quarantined in total")
