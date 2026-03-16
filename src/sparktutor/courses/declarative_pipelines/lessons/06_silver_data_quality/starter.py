"""
Silver — Data Quality Rules (Starter)

Implement DataQualityChecker with rules for ShopStream orders.
Rules: amount > 0, customer_id not null, order_id not null.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType, DoubleType


class DataQualityChecker:
    def __init__(self, rules):
        """
        rules: list of (name, condition) where condition is a Column expr
        """
        self.rules = rules

    def check(self, df):
        """
        Returns (valid_df, invalid_df).
        invalid_df gets _quarantine_reason and _quarantine_at.
        """
        # TODO: Build combined condition from all rules
        # TODO: Split into valid and invalid
        # TODO: Add _quarantine_reason to invalid (which rule failed)
        # TODO: Add _quarantine_at to invalid
        return (None, None)


# ---- Test harness (do not modify below this line) ----
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
