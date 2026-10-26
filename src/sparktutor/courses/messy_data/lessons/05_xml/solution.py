"""
XML - Solution

Read an orders export where each <order> has attributes, an optional
<coupon>, and one to three <item> children, and get one row per item in
two ways: with an inferred struct schema, and with VARIANT, where one
child and several children have different shapes. Then parse XML
snippets stored inside a string column.
"""

from pyspark.sql import SparkSession, functions as F


def read_orders(spark, path):
    """One row per <order>, with the schema inferred from the file."""
    return spark.read.option("rowTag", "order").xml(path)


def items_from_struct(orders):
    """One row per item: order_id, sku, qty (from the inferred struct schema)."""
    return (orders
            .select(F.col("_id").alias("order_id"), F.explode("items.item").alias("it"))
            .select("order_id",
                    F.col("it._sku").alias("sku"),
                    F.col("it.qty").cast("int").alias("qty")))


def read_orders_variant(spark, path):
    """One row per <order>, the whole element as one VARIANT column `v`."""
    return (spark.read
            .option("rowTag", "order")
            .option("singleVariantColumn", "v")
            .xml(path))


def items_from_variant(spark, ov):
    """One row per item: order_id, sku, qty (from VARIANT).

    A single <item> is an OBJECT and several are an ARRAY, so normalize
    every order to an array first.
    """
    ov.createOrReplaceTempView("orders_v")
    return spark.sql("""
        WITH norm AS (
          SELECT v:_id::bigint AS order_id,
                 CASE WHEN schema_of_variant(v:items.item) LIKE 'ARRAY%'
                      THEN v:items.item::array<variant>
                      ELSE array(v:items.item)
                 END AS items
          FROM orders_v
        )
        SELECT order_id,
               it:_sku::string AS sku,
               it:qty::int     AS qty
        FROM norm
        LATERAL VIEW explode(items) t AS it
    """)


def parse_prices(df):
    """`df` has an `xml` column like <price cur="CAD">4.5</price>.

    Returns the original columns plus amount (double) and currency (string).
    """
    parsed = F.from_xml("xml", "_VALUE DOUBLE, _cur STRING")
    return df.select("*", parsed.alias("p")).select(
        *df.columns,
        F.col("p._VALUE").alias("amount"),
        F.col("p._cur").alias("currency"))


# ---- Test harness ----
if __name__ == "__main__":
    import xml.etree.ElementTree as ET

    spark = (SparkSession.builder
             .appName("XmlOrders")
             .master("local[*]")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    XML = "data/messy/xml/orders.xml"

    # Expected answers, from the standard library XML parser
    root = ET.parse(XML).getroot()
    expected_items = sorted((int(o.get("id")), it.get("sku"), int(it.findtext("qty")))
                            for o in root.findall("order") for it in o.find("items").findall("item"))
    expected_coupons = sum(1 for o in root.findall("order") if o.find("coupon") is not None)
    single_item_orders = sorted(int(o.get("id")) for o in root.findall("order")
                                if len(o.find("items").findall("item")) == 1)

    try:
        orders = read_orders(spark, XML)
        assert orders is not None, "read_orders() returned None: complete TODO 1"
        assert orders.count() == 10, f"Expected 10 orders, got {orders.count()}. Use option('rowTag', 'order')"
        cols = set(orders.columns)
        assert {"_id", "_channel", "customer", "items", "coupon"} <= cols, (
            f"Columns should include _id and _channel (attributes get the _ prefix), customer, items, coupon; got {cols}")
        coupons = orders.filter(F.col("coupon").isNotNull()).count()
        assert coupons == expected_coupons, f"Expected {expected_coupons} orders with a coupon, got {coupons}"

        s_items = items_from_struct(orders)
        assert s_items is not None, "items_from_struct() returned None: complete TODO 2"
        assert s_items.columns == ["order_id", "sku", "qty"], f"columns: {s_items.columns}"
        got_s = sorted((r["order_id"], r["sku"], r["qty"]) for r in s_items.collect())
        assert got_s == expected_items, (
            f"Struct path items differ.\n expected {expected_items}\n got      {got_s}")

        ov = read_orders_variant(spark, XML)
        assert ov is not None, "read_orders_variant() returned None: complete TODO 3"
        assert dict(ov.dtypes).get("v") == "variant", f"Expected one VARIANT column v, got {ov.dtypes}"
        ov.createOrReplaceTempView("orders_v")
        shapes = {r["id"]: r["t"] for r in spark.sql(
            "SELECT v:_id::bigint AS id, schema_of_variant(v:items.item) AS t FROM orders_v").collect()}
        objects = sorted(i for i, t in shapes.items() if t.startswith("OBJECT"))
        assert objects == single_item_orders, (
            f"In VARIANT mode, orders with one <item> should be OBJECTs: expected {single_item_orders}, got {objects}")

        v_items = items_from_variant(spark, ov)
        assert v_items is not None, "items_from_variant() returned None: complete TODO 4"
        assert v_items.columns == ["order_id", "sku", "qty"], f"columns: {v_items.columns}"
        got_v = sorted((r["order_id"], r["sku"], r["qty"]) for r in v_items.collect())
        assert got_v == expected_items, (
            f"VARIANT path items differ (did the single-item orders {single_item_orders} go missing?).\n"
            f" expected {expected_items}\n got      {got_v}")

        prices = spark.createDataFrame(
            [(1, '<price cur="CAD">4.5</price>'), (2, '<price cur="USD">12</price>'), (3, '<price>7.25</price>')],
            ["id", "xml"])
        parsed = parse_prices(prices)
        assert parsed is not None, "parse_prices() returned None: complete TODO 5"
        got_p = sorted((r["id"], r["amount"], r["currency"]) for r in parsed.collect())
        assert got_p == [(1, 4.5, "CAD"), (2, 12.0, "USD"), (3, 7.25, None)], (
            f"Prices parsed as {got_p}. The element's text is _VALUE and the attribute cur is _cur")

        print("Orders (struct schema):")
        orders.orderBy("_id").show(truncate=False)
        print("Shape of items.item per order in VARIANT mode:")
        spark.sql("SELECT v:_id::bigint AS id, schema_of_variant(v:items.item) AS t FROM orders_v ORDER BY id").show(truncate=False)
        print("Items per order, both ways:")
        (s_items.groupBy("order_id").agg(F.count("*").alias("struct_items"))
            .join(v_items.groupBy("order_id").agg(F.count("*").alias("variant_items")), "order_id")
            .orderBy("order_id").show())
        print("Parsed prices:")
        parsed.show(truncate=False)
        print("All tests passed!")
    finally:
        spark.stop()
