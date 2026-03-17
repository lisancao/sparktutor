"""
Python UDTFs — Order Line Exploder

UDTF that explodes nested order line items with validation.
"""

from pyspark.sql import SparkSession, DataFrame, functions as f
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, DoubleType, ArrayType

ORDERS_DATA = [
    ("o1", [{"product_id": "p1", "quantity": 2, "price": 29.99}, {"product_id": "p2", "quantity": 1, "price": 49.99}]),
    ("o2", [{"product_id": "p1", "quantity": 0, "price": 29.99}, {"product_id": "p3", "quantity": 3, "price": 19.99}]),
]
ORDERS_SCHEMA = StructType([
    StructField("order_id", StringType()),
    StructField("line_items", ArrayType(StructType([
        StructField("product_id", StringType()),
        StructField("quantity", IntegerType()),
        StructField("price", DoubleType()),
    ]))),
])


def explode_order_lines(spark) -> DataFrame:
    """
    Explode order line items. Skip items with quantity <= 0.
    Try Spark 4 UDTF first; fall back to explode + filter on Spark 3.
    """
    df = spark.createDataFrame(ORDERS_DATA, ORDERS_SCHEMA)

    try:
        from pyspark.sql.functions import udtf

        @udtf(returnType="order_id: string, product_id: string, quantity: int, price: double, line_total: double")
        class ExplodeLines:
            def eval(self, order_id: str, line_items):
                for item in line_items:
                    if item["quantity"] > 0:
                        yield (order_id, item["product_id"], item["quantity"],
                               item["price"], item["quantity"] * item["price"])

        df.createOrReplaceTempView("orders_raw")
        return spark.sql("""
            SELECT t.* FROM orders_raw,
            LATERAL ExplodeLines(order_id, line_items) t
        """)
    except (ImportError, AttributeError, Exception):
        exploded = df.withColumn("item", f.explode("line_items"))
        return (
            exploded
            .filter(f.col("item.quantity") > 0)
            .select(
                "order_id",
                f.col("item.product_id").alias("product_id"),
                f.col("item.quantity").alias("quantity"),
                f.col("item.price").alias("price"),
                (f.col("item.quantity") * f.col("item.price")).alias("line_total"),
            )
        )


# ---- Test harness ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("UDTF").master("local[*]").getOrCreate()
    result = explode_order_lines(spark)
    assert result is not None, "Function returned None"
    rows = result.collect()
    assert len(rows) == 4, f"Expected 4 rows (skip qty=0), got {len(rows)}"
    assert "order_id" in result.columns and "product_id" in result.columns
    assert "line_total" in result.columns
    zero_qty = [r for r in rows if r.quantity == 0]
    assert len(zero_qty) == 0, "Should skip quantity <= 0"
    print("All tests passed!")
    result.show(truncate=False)
    spark.stop()
