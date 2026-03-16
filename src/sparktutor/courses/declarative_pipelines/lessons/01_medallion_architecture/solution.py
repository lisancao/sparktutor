"""
ShopStream Pipeline — Categorize Transforms (Solution)

Maps each transform to its medallion layer.
"""


def categorize_transform(transform_name):
    """
    Return the medallion layer for a given transform.
    Returns "bronze", "silver", "gold", or "unknown".
    """
    mapping = {
        "add_metadata_columns": "bronze",
        "deduplicate_by_event_id": "bronze",
        "cast_price_to_double": "silver",
        "validate_email_format": "silver",
        "join_product_catalog": "silver",
        "daily_revenue_by_category": "gold",
        "hourly_conversion_rates": "gold",
    }
    return mapping.get(transform_name, "unknown")


# ---- Test harness ----
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
