"""
Complex Types and Higher-Order Functions - Exercise

data/messy/nested/orders.json holds web shop orders, one JSON object per
line, nested a few levels deep:

    order_id, placed_at,
    customer {id, name, email, address {city, country, geo {lat, lon}}},
    lines    [ {sku, qty, unit_price, discounts [{code, pct}], attrs {any keys}} ],
    tags     [ strings ],
    payments [ {method, amount} ],
    status_history [ {status, at} ]

and the usual mess: tags in mixed case with spaces, duplicates and a null,
missing and empty arrays, a NULL quantity, free-form attrs objects whose keys
change from line to line, country codes in mixed case and status histories
out of time order.

Work on the nested values directly (structs, arrays, maps and higher-order
functions), explode only where one row per element is really wanted, and
flatten what is left by walking the schema.
"""

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import StructType

# attrs is declared as a MAP: its keys differ from line to line, so a struct
# (one fixed field per key) is the wrong shape for it.
ORDER_SCHEMA = """
    order_id STRING,
    placed_at TIMESTAMP,
    customer STRUCT<id: STRING, name: STRING, email: STRING,
                    address: STRUCT<city: STRING, country: STRING,
                                    geo: STRUCT<lat: DOUBLE, lon: DOUBLE>>>,
    lines ARRAY<STRUCT<sku: STRING, qty: INT, unit_price: DOUBLE,
                       discounts: ARRAY<STRUCT<code: STRING, pct: INT>>,
                       attrs: MAP<STRING, STRING>>>,
    tags ARRAY<STRING>,
    payments ARRAY<STRUCT<method: STRING, amount: DOUBLE>>,
    status_history ARRAY<STRUCT<status: STRING, at: TIMESTAMP>>
"""


def read_orders(spark, path):
    """Read the orders with ORDER_SCHEMA."""
    # TODO 1: spark.read.schema(ORDER_SCHEMA).json(path)
    return None


def order_summary(orders):
    """One row per order, computed without exploding anything.

    order_id
    n_lines        number of lines (0 when lines is missing or empty)
    total_qty      sum of qty over the lines, a NULL qty counting as 0 (0 for no lines)
    gross          sum of qty * unit_price as a double (0.0 for no lines)
    skus           sorted distinct SKUs ([] for no lines)
    clean_tags     tags trimmed, lower-cased, without NULLs or duplicates, sorted ([] when missing)
    latest_status  the status of the history entry with the latest `at`
    has_engraving  true if any line has an "engraving" key in attrs (false for no lines)
    """
    # TODO 2: start with
    #   lines = F.coalesce("lines", F.array())    # a missing array becomes []
    #   tags = F.coalesce("tags", F.array())
    # then build each column with size, aggregate (zero F.lit(0) for qty,
    # F.lit(0.0) for gross), lines.sku, array_distinct, array_sort, transform,
    # filter, exists and map_contains_key. For latest_status, sort
    # status_history by `at` with array_sort(col, comparator) and take
    # F.element_at(sorted, -1).status
    return None


def redact_customer(orders):
    """The orders with customer.email removed and customer.address.country upper-cased."""
    # TODO 3: withColumn("customer", F.col("customer").dropFields(...).withField(...))
    return None


def attr_profile(orders):
    """Which attrs keys occur: key, n (lines that have it), values (sorted distinct values). Sorted by key."""
    # TODO 4: explode lines into one row per line, explode line.attrs (a map
    # explodes into key and value columns), then group by key
    return None


def flatten_structs(df):
    """Turn every struct field, at any depth, into a top-level column named a_b_c.

    Arrays and maps are kept as they are: their elements cannot become columns.
    """
    # TODO 5: walk df.schema recursively. For a field whose dataType is a
    # StructType, recurse with the path so far; otherwise select
    # F.col(<path with each part in backticks, joined by ".">) aliased to
    # "_".join(path)
    return None


def lines_long(orders):
    """One row per order line: order_id, line_no (1-based), sku, qty, unit_price, discount_pct.

    discount_pct is the sum of the line's discount percentages (0 when none).
    An order without lines keeps one row, with NULL in every line column.
    """
    # TODO 6: posexplode_outer("lines") aliased ("pos", "line"), then select the
    # fields; discount_pct is an aggregate over line.discounts
    return None


def skus_in_line_order(lines):
    """From lines_long's output back to one row per order: order_id, skus (in line order).

    Orders without lines are left out. collect_list alone does not promise
    any order, so collect (line_no, sku) pairs, sort them and keep the SKUs.
    """
    # TODO 7: filter out the NULL line_no rows, group by order_id,
    # array_sort(collect_list(struct("line_no", "sku"))), then transform to the sku
    return None


# ---- Test harness ----
if __name__ == "__main__":
    import json
    from collections import defaultdict

    spark = (SparkSession.builder
             .appName("ComplexTypes")
             .master("local[*]")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    PATH = "data/messy/nested/orders.json"

    # The expected answers, computed from the file with plain Python
    raw = [json.loads(line) for line in open(PATH)]
    want_summary = {}
    want_attrs = defaultdict(lambda: [0, set()])
    want_lines = []
    for r in raw:
        lines = r.get("lines") or []
        tags = r.get("tags") or []
        history = sorted(r["status_history"], key=lambda h: h["at"])
        want_summary[r["order_id"]] = {
            "n_lines": len(lines),
            "total_qty": sum(l["qty"] or 0 for l in lines),
            "gross": round(sum((l["qty"] or 0) * l["unit_price"] for l in lines), 2),
            "skus": sorted({l["sku"] for l in lines}),
            "clean_tags": sorted({t.strip().lower() for t in tags if t is not None}),
            "latest_status": history[-1]["status"],
            "has_engraving": any("engraving" in l["attrs"] for l in lines),
        }
        for l in lines:
            for k, v in l["attrs"].items():
                want_attrs[k][0] += 1
                want_attrs[k][1].add(v)
        if not lines:
            want_lines.append((r["order_id"], None, None, None, None, None))
        for i, l in enumerate(lines, start=1):
            want_lines.append((r["order_id"], i, l["sku"], l["qty"], l["unit_price"],
                               sum(d["pct"] for d in l["discounts"])))

    try:
        orders = read_orders(spark, PATH)
        assert orders is not None, "read_orders() returned None: complete TODO 1"
        types = dict(orders.dtypes)
        assert orders.count() == len(raw), f"Expected {len(raw)} orders, got {orders.count()}"
        assert types.get("lines", "").startswith("array<struct<sku:string,qty:int"), (
            f"lines should come from ORDER_SCHEMA, got {types.get('lines')}. Use spark.read.schema(ORDER_SCHEMA)")
        assert "attrs:map<string,string>" in types["lines"], "attrs should be a MAP<STRING, STRING>"
        orders = orders.cache()

        summary = order_summary(orders)
        assert summary is not None, "order_summary() returned None: complete TODO 2"
        expected_cols = ["order_id", "n_lines", "total_qty", "gross", "skus", "clean_tags",
                         "latest_status", "has_engraving"]
        assert summary.columns == expected_cols, f"order_summary columns should be {expected_cols}, got {summary.columns}"
        got = {r["order_id"]: r.asDict() for r in summary.collect()}
        assert len(got) == len(raw), f"order_summary should keep every order ({len(raw)}), got {len(got)} rows"
        for oid, want in want_summary.items():
            row = got[oid]
            for key, value in want.items():
                actual = row[key]
                if key == "gross" and actual is not None:
                    actual = round(actual, 2)
                hint = ""
                if actual is None:
                    hint = (" A NULL usually means a NULL array went into the function: "
                            "coalesce lines and tags with F.array() first, and qty with 0")
                elif key == "clean_tags":
                    hint = " Trim and lower-case each tag (transform), drop NULLs (filter), then array_distinct and array_sort"
                elif key == "latest_status":
                    hint = " Sort status_history by `at` (array_sort with a comparator), then take the last element"
                assert actual == value, f"{oid}: {key} should be {value!r}, got {actual!r}.{hint}"

        red = redact_customer(orders)
        assert red is not None, "redact_customer() returned None: complete TODO 3"
        assert red.columns == orders.columns, f"redact_customer should keep the columns {orders.columns}, got {red.columns}"
        cust_fields = red.schema["customer"].dataType.fieldNames()
        assert "email" not in cust_fields, f"customer.email should be dropped (dropFields), customer has {cust_fields}"
        assert cust_fields == ["id", "name", "address"], f"customer should keep id, name and address, got {cust_fields}"
        countries = sorted({r[0] for r in red.select("customer.address.country").collect()})
        assert countries == ["CA", "US", "VN"], (
            f"Countries should be upper-cased with withField('address.country', ...), got {countries}")
        geo = red.filter("order_id = 'O-1001'").select("customer.address.geo.lat").first()[0]
        assert geo == raw[0]["customer"]["address"]["geo"]["lat"], "The rest of customer.address must be unchanged"

        prof = attr_profile(orders)
        assert prof is not None, "attr_profile() returned None: complete TODO 4"
        got_prof = [(r["key"], r["n"], r["values"]) for r in prof.collect()]
        want_prof = [(k, n, sorted(v)) for k, (n, v) in sorted(want_attrs.items())]
        assert got_prof == want_prof, f"attr_profile should be {want_prof}, got {got_prof}"

        flat = flatten_structs(orders)
        assert flat is not None, "flatten_structs() returned None: complete TODO 5"
        want_flat = ["order_id", "placed_at", "customer_id", "customer_name", "customer_email",
                     "customer_address_city", "customer_address_country", "customer_address_geo_lat",
                     "customer_address_geo_lon", "lines", "tags", "payments", "status_history"]
        assert flat.columns == want_flat, f"flatten_structs(orders) columns should be {want_flat}, got {flat.columns}"
        assert dict(flat.dtypes)["customer_address_geo_lat"] == "double", "Leaf types must be kept"
        assert flat.filter("customer_address_geo_lat IS NULL").count() == 1, (
            "One order has no geo, so exactly one customer_address_geo_lat is NULL")
        odd = spark.sql("SELECT 1 AS id, named_struct('x.y', named_struct('z', 2), 'w', array(3)) AS `a b`")
        odd_flat = flatten_structs(odd)
        assert odd_flat.columns == ["id", "a b_x.y_z", "a b_w"], (
            f"Names with dots and spaces must survive: expected ['id', 'a b_x.y_z', 'a b_w'], got {odd_flat.columns}. "
            "Quote each part of the path with backticks")
        assert odd_flat.first()["a b_x.y_z"] == 2

        long = lines_long(orders)
        assert long is not None, "lines_long() returned None: complete TODO 6"
        assert long.columns == ["order_id", "line_no", "sku", "qty", "unit_price", "discount_pct"], (
            f"lines_long columns are {long.columns}")
        got_lines = sorted((tuple(r) for r in long.collect()), key=lambda t: (t[0], t[1] or 0))
        want_sorted = sorted(want_lines, key=lambda t: (t[0], t[1] or 0))
        assert len(got_lines) == len(want_sorted), (
            f"lines_long should have {len(want_sorted)} rows (one per line plus one per order without lines), "
            f"got {len(got_lines)}. Use posexplode_outer, not posexplode")
        assert got_lines == want_sorted, (
            f"lines_long rows differ. First expected {want_sorted[:3]}, got {got_lines[:3]}. "
            "line_no is pos + 1, and discount_pct sums line.discounts with aggregate")

        rebuilt = skus_in_line_order(long)
        assert rebuilt is not None, "skus_in_line_order() returned None: complete TODO 7"
        got_rebuilt = {r["order_id"]: r["skus"] for r in rebuilt.collect()}
        want_rebuilt = {r["order_id"]: [l["sku"] for l in r["lines"]] for r in raw if r.get("lines")}
        assert got_rebuilt == want_rebuilt, (
            f"skus_in_line_order should give the SKUs in line order for orders with lines. "
            f"Expected for O-1004: {want_rebuilt.get('O-1004')}, got {got_rebuilt.get('O-1004')}")

        print("Order summary:")
        summary.orderBy("order_id").show(8, truncate=False)
        print("Redacted customer:")
        red.select("order_id", "customer").show(3, truncate=False)
        print("Attribute keys:")
        prof.show(truncate=False)
        print("Flattened columns:", flat.columns)
        print("Lines, long form:")
        long.orderBy("order_id", "line_no").show(8)
        print("All tests passed!")
    finally:
        spark.stop()
