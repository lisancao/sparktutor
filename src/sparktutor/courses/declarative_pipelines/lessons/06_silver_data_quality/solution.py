"""
Silver — Data Quality Rules (Solution)

DataQualityChecker with rule-based validation and quarantine.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType


class DataQualityChecker:
    def __init__(self, rules):
        self.rules = rules

    def check(self, df):
        passes = f.lit(True)
        for name, cond in self.rules:
            passes = passes & cond
        valid = df.filter(passes)
        invalid = df.filter(~passes)
        fail_cols = []
        for i, (name, cond) in enumerate(self.rules):
            invalid = invalid.withColumn(f"_fail_{i}", f.when(~cond, f.lit(name)))
            fail_cols.append(f.col(f"_fail_{i}"))
        invalid = invalid.withColumn("_quarantine_reason", f.coalesce(*fail_cols))
        invalid = invalid.drop(*[f"_fail_{i}" for i in range(len(self.rules))])
        invalid = invalid.withColumn("_quarantine_at", f.current_timestamp())
        return (valid, invalid)


# ---- Test harness ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("DQCheck").master("local[*]").getOrCreate()

    orders_data = [
        ("o1", "c1", 99.99),
        ("o2", "c2", 49.99),
        ("o3", "c3", -5.0),
    ]
    schema = StructType([
        StructField("order_id", StringType()),
        StructField("customer_id", StringType()),
        StructField("amount", DoubleType()),
    ])
    orders_df = spark.createDataFrame(orders_data, schema)

    rules = [
        ("amount_positive", f.col("amount") > 0),
        ("customer_not_null", f.col("customer_id").isNotNull()),
        ("order_id_not_null", f.col("order_id").isNotNull()),
    ]
    checker = DataQualityChecker(rules)
    valid, invalid = checker.check(orders_df)

    assert valid.count() == 2, f"valid: expected 2, got {valid.count()}"
    assert invalid.count() == 1, f"invalid: expected 1, got {invalid.count()}"
    assert "_quarantine_reason" in invalid.columns
    assert "_quarantine_at" in invalid.columns
    print("All tests passed!")
    spark.stop()
