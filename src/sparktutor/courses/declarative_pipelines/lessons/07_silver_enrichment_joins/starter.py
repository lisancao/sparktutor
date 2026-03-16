"""
Silver — Enrichment Joins (Starter)

Implement enrich_clicks(spark, clicks_df, products_df, users_df) that
joins clicks with product names and user segments.
"""

from pyspark.sql import SparkSession, functions as f


def enrich_clicks(spark, clicks_df, products_df, users_df):
    """
    Enrich clicks with product_name, category from products and segment from users.
    Use left joins. Broadcast small lookups.
    """
    # TODO: Join clicks with products on product_id (left)
    # TODO: Join result with users on user_id (left)
    # TODO: Use f.broadcast() for products and users
    return None


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = SparkSession.builder.appName("Enrich").master("local[*]").getOrCreate()

    clicks_data = [("e1", "u1", "p1"), ("e2", "u2", "p2")]
    clicks_df = spark.createDataFrame(clicks_data, ["event_id", "user_id", "product_id"])

    products_data = [("p1", "Widget", "Electronics"), ("p2", "Gadget", "Home")]
    products_df = spark.createDataFrame(products_data, ["product_id", "product_name", "category"])

    users_data = [("u1", "premium"), ("u2", "standard")]
    users_df = spark.createDataFrame(users_data, ["user_id", "segment"])

    enriched = enrich_clicks(spark, clicks_df, products_df, users_df)
    assert enriched is not None
    assert enriched.count() == 2
    assert "product_name" in enriched.columns
    assert "category" in enriched.columns
    assert "segment" in enriched.columns
    print("All tests passed!")
    spark.stop()
