"""
ShopStream Pipeline — Categorize Transforms (Starter)

Implement `categorize_transform(transform_name)` that returns the layer
("bronze", "silver", or "gold") for each ShopStream transform.

Bronze: ingest, metadata, deduplication
Silver: type casting, validation, enrichment/joins
Gold: aggregations, KPIs, dashboards
"""


def categorize_transform(transform_name):
    """
    Return the medallion layer for a given transform.
    Returns "bronze", "silver", "gold", or "unknown".
    """
    # TODO: Implement the mapping for these transforms:
    # add_metadata_columns, deduplicate_by_event_id -> bronze
    # cast_price_to_double, validate_email_format, join_product_catalog -> silver
    # daily_revenue_by_category, hourly_conversion_rates -> gold
    pass


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    assert categorize_transform("add_metadata_columns") == "bronze"
    assert categorize_transform("deduplicate_by_event_id") == "bronze"
    assert categorize_transform("cast_price_to_double") == "silver"
    assert categorize_transform("validate_email_format") == "silver"
    assert categorize_transform("join_product_catalog") == "silver"
    assert categorize_transform("daily_revenue_by_category") == "gold"
    assert categorize_transform("hourly_conversion_rates") == "gold"
    assert categorize_transform("unknown_thing") == "unknown"
    print("All tests passed!")
