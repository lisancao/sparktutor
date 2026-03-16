"""
Gold — Window Functions (Solution)

Executive dashboard with rankings, running totals, moving average, and pct change.
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql import Window


def gold_executive_dashboard(daily_revenue_df):
    """
    Add rank (by revenue within category), running_revenue, ma7, pct_change.
    """
    w_rank = Window.partitionBy("category").orderBy(f.col("revenue").desc())
    w_running = Window.orderBy("date").rowsBetween(Window.unboundedPreceding, Window.currentRow)
    w_ma7 = Window.orderBy("date").rowsBetween(-6, 0)
    w_lag = Window.partitionBy("category", "product_id").orderBy("date")

    result = (daily_revenue_df
        .withColumn("rank", f.row_number().over(w_rank))
        .withColumn("running_revenue", f.sum("revenue").over(w_running))
        .withColumn("ma7", f.avg("revenue").over(w_ma7))
        .withColumn("prev_revenue", f.lag("revenue", 1).over(w_lag))
        .withColumn("pct_change",
            f.when(f.col("prev_revenue").isNotNull() & (f.col("prev_revenue") != 0),
                (f.col("revenue") - f.col("prev_revenue")) / f.col("prev_revenue"))
            .otherwise(None))
        .drop("prev_revenue"))
    return result


# ---- Test harness ----
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
