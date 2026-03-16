"""
Default Column Values & Table Features — Create Product and Order Tables

Create product and order_lines tables with DEFAULT and GENERATED ALWAYS AS.
"""

from pyspark.sql import SparkSession

def create_ecommerce_tables(spark):
    """
    Create products and order_lines tables with:
    - products: product_id, name, category DEFAULT 'Uncategorized'
    - order_lines: order_id, product_id, quantity, unit_price,
      line_total GENERATED ALWAYS AS (quantity * unit_price)

    Use a temp location (e.g. /tmp/sparktutor/products, /tmp/sparktutor/order_lines).
    Return list of table names created: ["products", "order_lines"].

    If Delta is not available, use PARQUET or default format.
    """
    base_path = "/tmp/sparktutor"

    # TODO: CREATE TABLE products with DEFAULT on category
    # TODO: CREATE TABLE order_lines with GENERATED ALWAYS AS for line_total

    pass


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("TableFeatures").master("local[*]").getOrCreate()
    try:
        tables = create_ecommerce_tables(spark)
        assert tables is not None, "Function returned None"
        assert "products" in tables and "order_lines" in tables
        spark.sql("INSERT INTO products (product_id, name) VALUES ('p1', 'Widget')")
        spark.sql("INSERT INTO order_lines (order_id, product_id, quantity, unit_price) VALUES ('o1', 'p1', 2, 29.99)")
        rows = spark.sql("SELECT * FROM order_lines").collect()
        assert len(rows) == 1
        assert hasattr(rows[0], "line_total") or "line_total" in rows[0].asDict()
        line_total = rows[0].line_total if hasattr(rows[0], "line_total") else rows[0]["line_total"]
        assert abs(float(line_total) - 59.98) < 0.01
        print("All tests passed!")
    except Exception as e:
        if "GENERATED" in str(e) or "Delta" in str(e) or "syntax" in str(e).lower():
            print(f"Note: Some features may require Spark 4 + Delta: {e}")
        else:
            raise
    spark.stop()
