"""
Gold — Window Functions (Starter)

Implement gold_executive_dashboard(daily_revenue_df) with rank,
running_revenue, ma7, and pct_change.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql import Window


def gold_executive_dashboard(daily_revenue_df):
    """
    Add rank (by revenue within category), running_revenue, ma7, pct_change.
    """
    # TODO: rank = row_number over partitionBy category, orderBy revenue desc
    # TODO: running_revenue = sum over rowsBetween unboundedPreceding, currentRow
    # TODO: ma7 = avg over rowsBetween(-6, 0)
    # TODO: pct_change = (revenue - lag(revenue)) / lag(revenue)
    return None


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("GoldWindow").master("local[*]").getOrCreate()

    data = [
        ("2024-01-01", "Electronics", "p1", 100.0),
        ("2024-01-02", "Electronics", "p1", 150.0),
        ("2024-01-03", "Electronics", "p1", 120.0),
        ("2024-01-01", "Home", "p2", 80.0),
        ("2024-01-02", "Home", "p2", 90.0),
    ]
    df = spark.createDataFrame(data, ["date", "category", "product_id", "revenue"])
    df = df.withColumn("date", f.to_date("date"))

    result = gold_executive_dashboard(df)
    assert result is not None
    assert "rank" in result.columns
    assert "running_revenue" in result.columns
    assert "ma7" in result.columns
    assert "pct_change" in result.columns
    assert result.count() == 5
    print("All tests passed!")
    spark.stop()
