"""
Pipe Syntax and QUALIFY - Solution

Rewrite nested SQL as pipelines and filter window results with QUALIFY.
"""

from pyspark.sql import SparkSession


ORDERS = [
    (1, "c1", "east", "widget", 30, "2024-03-01"),
    (2, "c1", "east", "gadget", 10, "2024-03-05"),
    (3, "c2", "west", "widget", 25, "2024-03-02"),
    (4, "c2", "west", "gizmo", 40, "2024-03-09"),
    (5, "c3", "west", "widget", 5, "2024-03-03"),
    (6, "c3", "east", "gadget", 50, "2024-03-08"),
    (7, "c1", "east", "widget", 20, "2024-03-07"),
]


def pipe_report(spark):
    """Return four DataFrames built with pipe syntax and QUALIFY."""

    spark.createDataFrame(
        ORDERS, "order_id int, customer string, region string, product string, amount int, order_date string"
    ).createOrReplaceTempView("orders")

    # 1. Revenue per region for orders over 5, biggest first (pipe syntax, 4.0).
    region_revenue = spark.sql("""
        FROM orders
        |> WHERE amount > 5
        |> AGGREGATE sum(amount) AS revenue, count(*) AS n GROUP BY region
        |> ORDER BY revenue DESC
    """)

    # 2. The same aggregation with the 4.2 additions: `|` as the pipe token
    #    and aggregate functions directly in a pipe SELECT.
    region_revenue_42 = spark.sql("""
        FROM orders
        | WHERE amount > 5
        | SELECT region, sum(amount) AS revenue, count(*) AS n GROUP BY region
        | ORDER BY revenue DESC
    """)

    # 3. Latest order per customer with QUALIFY (4.2).
    latest_per_customer = spark.sql("""
        SELECT customer, order_id, order_date
        FROM orders
        QUALIFY row_number() OVER (PARTITION BY customer ORDER BY order_date DESC) = 1
        ORDER BY customer
    """)

    # 4. Top product per region by revenue: pipe syntax with EXTEND, a
    #    window function, and a WHERE on its result.
    top_product = spark.sql("""
        FROM orders
        |> AGGREGATE sum(amount) AS revenue GROUP BY region, product
        |> EXTEND rank() OVER (PARTITION BY region ORDER BY revenue DESC) AS rk
        |> WHERE rk = 1
        |> DROP rk
        |> ORDER BY region
    """)

    return {
        "region_revenue": region_revenue,
        "region_revenue_42": region_revenue_42,
        "latest_per_customer": latest_per_customer,
        "top_product": top_product,
    }


# ---- Test harness ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("PipeSyntaxTest")
        .master("local[*]")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate())

    result = pipe_report(spark)
    assert result is not None, "Function returned None"
    rr = [tuple(r) for r in result["region_revenue"].collect()]
    assert rr == [("east", 110, 4), ("west", 65, 2)], f"Unexpected region revenue: {rr}"
    rr42 = [tuple(r) for r in result["region_revenue_42"].collect()]
    assert rr42 == rr, "The 4.2 pipe form should match the AGGREGATE form"
    latest = {r["customer"]: r["order_id"] for r in result["latest_per_customer"].collect()}
    assert latest == {"c1": 7, "c2": 4, "c3": 6}, f"Unexpected latest orders: {latest}"
    top = [tuple(r) for r in result["top_product"].collect()]
    assert top == [("east", "gadget", 60), ("west", "gizmo", 40)], f"Unexpected top products: {top}"
    assert result["top_product"].columns == ["region", "product", "revenue"]
    for name, df in result.items():
        print(name)
        df.show()
    print("All tests passed!")
    spark.stop()
