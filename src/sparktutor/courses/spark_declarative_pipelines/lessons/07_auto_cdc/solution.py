# spark-pipelines: dry-run
"""
Lesson 7: Current Customers from a Change Feed (solution)

On an Iceberg target this produces c-01 in Hanoi (seq 5 beats the late
seq 4), c-03 in Montreal, and no c-02 (deleted at seq 6).
"""

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

spark: SparkSession

CHANGE_SCHEMA = "customer_id STRING, name STRING, city STRING, op STRING, seq INT"


@dp.table(comment="Raw customer change events", table_properties={"quality": "bronze"})
def bronze_customer_changes() -> DataFrame:
    return (
        spark.readStream.schema(CHANGE_SCHEMA).json("data/customer_changes")
        .withColumn("_source_file", F.col("_metadata.file_name"))
        .withColumn("_ingested_at", F.current_timestamp())
    )


dp.create_streaming_table("customers_current", comment="Current state of every customer (SCD Type 1)")

dp.create_auto_cdc_flow(
    target="customers_current",
    source="bronze_customer_changes",
    keys=["customer_id"],
    sequence_by="seq",
    apply_as_deletes=F.expr("op = 'DELETE'"),
    except_column_list=["op", "seq", "_source_file", "_ingested_at"],
    stored_as_scd_type=1,
)


@dp.materialized_view
def customers_by_city() -> DataFrame:
    return spark.table("customers_current").groupBy("city").agg(F.count("*").alias("customer_count"))
