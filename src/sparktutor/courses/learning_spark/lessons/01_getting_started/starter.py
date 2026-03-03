"""
M&M Candy Count Analysis - Starter Code

Implement the `mnm_analysis` function that:
1. Reads a CSV file with columns: State, Color, Count
2. Groups by State and Color, sums the Count column
3. Orders by the sum in descending order
4. Filters for California ('CA') only
5. Returns the California-only DataFrame

Based on the M&M count example from Learning Spark.
"""

from pyspark.sql import SparkSession, functions as f


def mnm_analysis(spark, file_path):
    """Analyze M&M candy counts from CSV data."""

    # TODO: Read the CSV file with header and inferSchema options
    mnm_df = None  # Replace with spark.read...

    # TODO: Group by State and Color, sum the Count column,
    #       and order by the sum descending
    count_mnm_df = None  # Replace

    # TODO: Filter for California ('CA') only
    ca_count_mnm_df = None  # Replace

    return ca_count_mnm_df


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    import tempfile, os

    spark = (SparkSession.builder
        .appName("MnMTest")
        .master("local[*]")
        .getOrCreate())

    # Create test CSV
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
