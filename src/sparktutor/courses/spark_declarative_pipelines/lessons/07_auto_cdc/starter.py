# spark-pipelines: dry-run
"""
Lesson 7: Current Customers from a Change Feed

Validated with `spark-pipelines dry-run`: Auto CDC targets need a table
format with MERGE support (Iceberg), which plain local Spark does not have.
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


# TODO: declare the customers_current streaming table


# TODO: dp.create_auto_cdc_flow(...) from bronze_customer_changes into customers_current:
#       keys customer_id, sequence_by seq, deletes where op = 'DELETE', SCD type 1,
#       excluding op, seq, _source_file and _ingested_at


# TODO: @dp.materialized_view
def customers_by_city() -> DataFrame:
    # TODO: city, customer_count from customers_current
    pass
