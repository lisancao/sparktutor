# spark-connectors: test-catalog
"""
Lesson 7: Current Customers from a Change Feed

The target lives in `mem`, Spark's in-memory test catalog with MERGE support
(see "What the Target Must Support" in the lesson). Expected result: c-01 in
Hanoi (seq 5 beats the late seq 4), c-03 in Montreal, and no c-02 (deleted at
seq 6).
"""

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

spark: SparkSession

CHANGE_SCHEMA = "customer_id STRING, name STRING, city STRING, op STRING, seq INT"
TARGET = "mem.crm.customers_current"


@dp.table(comment="Raw customer change events", table_properties={"quality": "bronze"})
def bronze_customer_changes() -> DataFrame:
    return (
        spark.readStream.schema(CHANGE_SCHEMA).json("data/customer_changes")
        .withColumn("_source_file", F.col("_metadata.file_name"))
        .withColumn("_ingested_at", F.current_timestamp())
    )


# TODO: declare the TARGET streaming table


# TODO: dp.create_auto_cdc_flow(...) from bronze_customer_changes into TARGET:
#       keys customer_id, sequence_by seq, deletes where op = 'DELETE', SCD type 1,
#       excluding op, seq, _source_file and _ingested_at


# TODO: @dp.materialized_view
def customers_by_city() -> DataFrame:
    # TODO: city, customer_count from TARGET
    pass


# The mem catalog lives inside the pipeline run, so this copy (in the default
# catalog) is what you see printed after the run.
@dp.materialized_view
def customers_current_preview() -> DataFrame:
    return spark.table(TARGET).select("customer_id", "name", "city")


# ---- Checks (do not modify below this line) ----
def _expect(table: str, condition: str, message: str) -> DataFrame:
    df = spark.table(table)
    return df.agg(F.expr(condition).alias("ok")).select(
        F.assert_true(F.col("ok"), f"{table}: {message}").alias("ok")
    )


@dp.materialized_view
def check_customers_current() -> DataFrame:
    return _expect(
        TARGET,
        "count(*) = 2 AND count_if(customer_id = 'c-02') = 0 "
        "AND max(CASE WHEN customer_id = 'c-01' THEN city END) = 'Hanoi'",
        "expected 2 customers, c-01 in Hanoi (seq 5 beats the late seq 4) and c-02 deleted",
    )


@dp.materialized_view
def check_customers_by_city() -> DataFrame:
    return _expect(
        "customers_by_city",
        "count(*) = 2 AND sum(customer_count) = 2",
        "expected one customer in each of 2 cities",
    )
