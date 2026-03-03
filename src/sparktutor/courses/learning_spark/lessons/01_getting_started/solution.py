"""
M&M Candy Count Analysis - Solution

Complete analysis pipeline: read CSV, aggregate by State+Color,
filter for California.
"""

from pyspark.sql import SparkSession, functions as f


def mnm_analysis(spark, file_path):
    """Analyze M&M candy counts from CSV data."""

    mnm_df = (spark.read.format("csv")
        .option("header", "true")
        .option("inferSchema", "true")
        .load(file_path))

    count_mnm_df = (mnm_df
        .groupBy("State", "Color")
        .agg(f.sum("Count").alias("Total"))
        .orderBy(f.col("Total").desc()))

    ca_count_mnm_df = count_mnm_df.filter(f.col("State") == "CA")

    return ca_count_mnm_df


# ---- Test harness ----
if __name__ == "__main__":
    import tempfile, os

    spark = (SparkSession.builder
        .appName("MnMTest")
        .master("local[*]")
        .getOrCreate())

    tmp = tempfile.mkdtemp()
    csv_path = os.path.join(tmp, "mnm_dataset.csv")
    with open(csv_path, "w") as fh:
        fh.write("State,Color,Count\n")
        fh.write("CA,Yellow,1230\n")
        fh.write("CA,Brown,1500\n")
        fh.write("TX,Green,1200\n")
        fh.write("TX,Red,1100\n")
        fh.write("CA,Yellow,800\n")
        fh.write("NY,Blue,900\n")

    df = mnm_analysis(spark, csv_path)
    assert df is not None, "Function returned None"
    states = [row.State for row in df.collect()]
    assert all(s == "CA" for s in states), f"Expected only CA rows, got {states}"
    assert df.count() == 2, f"Expected 2 CA color groups, got {df.count()}"
    print("All tests passed!")
    df.show(truncate=False)
    spark.stop()
