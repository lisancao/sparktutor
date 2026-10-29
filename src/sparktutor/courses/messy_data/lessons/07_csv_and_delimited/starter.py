"""
CSV and Delimited Files - Exercise

Five delimited files, five kinds of mess:
- products.csv: RFC 4180 quoting (doubled quotes), line breaks inside
  quoted fields, SKUs with leading zeros, "NA" for missing values
- orders_eu.csv: a byte order mark, "#" comment lines, ";" separator,
  decimal commas, dd.MM.yyyy dates and two bad rows
- legacy_latin1.tsv: tabs, ISO-8859-1, a duplicated and a blank header
- stores_fixed.txt: fixed-width records with a header and trailer record
- sales/: one feed whose columns were reordered and then extended

Read each one correctly, keep the bad rows instead of losing them, and
write a CSV that other tools read back exactly.
"""

from functools import reduce

from pyspark.sql import SparkSession, functions as F

# Columns that look like numbers but are identifiers stay STRING
PRODUCT_SCHEMA = """sku STRING, name STRING, description STRING, price DECIMAL(10,2),
                    in_stock STRING, updated_at TIMESTAMP"""

# The corrupt record column must be in the schema, as a STRING
ORDER_SCHEMA = """order_id INT, sku STRING, customer STRING, amount DECIMAL(10,2),
                  order_date DATE, note STRING, _corrupt_record STRING"""

# legacy_latin1.tsv's header is "id, name, city, name, (blank), notes"
LEGACY_NAMES = ["id", "first_name", "city", "display_name", "unused", "notes"]

# Target types for the sales feed, whatever order a file has its columns in
SALES_TYPES = {"id": "int", "amount": "decimal(10,2)", "day": "date", "currency": "string"}

# stores_fixed.txt: (name, first character, width), counting from 1
FIXED_LAYOUT = [("store_id", 1, 4), ("name", 5, 20), ("city", 25, 12),
                ("opened", 37, 8), ("sales_cents", 45, 10)]
FIXED_WIDTH = 54


def read_products(spark, path):
    """products.csv with quotes, line breaks and NA handled; in_stock as a boolean."""
    # TODO 1: spark.read with .schema(PRODUCT_SCHEMA) and the options
    #   header (true), multiLine (true: line breaks inside quoted fields),
    #   escape ('"': a doubled quote inside quotes is one literal quote) and
    #   nullValue ("NA"). Then turn in_stock ("yes"/"no") into a boolean with
    #   F.col("in_stock").try_cast("boolean").
    return None


def read_orders_eu(spark, path):
    """orders_eu.csv typed, with unparseable rows kept in _corrupt_record."""
    # TODO 2: .schema(ORDER_SCHEMA) (it ends with _corrupt_record STRING) and
    #   the options header, enforceSchema (false: check the header against the
    #   schema), sep (";"), comment ("#"), locale ("de-DE": decimal commas for
    #   DECIMAL columns) and dateFormat ("dd.MM.yyyy"). Add a "file" column from
    #   _metadata.file_name.
    return None


def read_legacy(spark, path):
    """legacy_latin1.tsv decoded from ISO-8859-1, with every column renamed."""
    # TODO 3: header, sep ("\t") and encoding ("ISO-8859-1"), then rename every
    #   column by position with .toDF(*LEGACY_NAMES)
    return None


def read_sales(spark, folder):
    """Every file in the sales folder, columns matched by name.

    Returns (sales, rejects):
      sales:   id, amount, day, currency, file for rows that parsed
      rejects: file, reason ("wrong_column_count" or "bad_value"), record
    """
    # TODO 4: list the files without reading them:
    #   paths = sorted(r.path for r in spark.read.format("binaryFile").load(folder)
    #                  .select("path").collect())
    #   For each path: header = spark.read.text(p).first()["value"].split(","),
    #   build a schema "`col1` STRING, `col2` STRING, ..., _corrupt_record STRING"
    #   in that file's order, read the file with it (header true) and add "file"
    #   from _metadata.file_name. Combine the files with
    #   unionByName(..., allowMissingColumns=True).
    raw = None

    # TODO 5: from `raw`, select file, _corrupt_record, a "record" column
    #   (concat_ws(",") of the SALES_TYPES columns, NULLs as ""), each raw column
    #   as <name>_raw, and each column try_cast to its SALES_TYPES type.
    #   reason = "wrong_column_count" when _corrupt_record is set, else
    #   "bad_value" when any <name>_raw is present but its typed column is NULL.
    #   Cache, then split: sales = rows without a reason (id, amount, day,
    #   currency, file); rejects = file, reason, and _corrupt_record (or record
    #   when that is NULL) as "record".
    sales, rejects = None, None
    return sales, rejects


def read_fixed(spark, path):
    """stores_fixed.txt as typed columns.

    Returns (stores, rejects): stores has store_id, name, city, opened
    (DATE) and sales (DECIMAL(12,2)); rejects has the raw `line` of every
    data record that is not exactly FIXED_WIDTH characters long. Header
    (HDR...) and trailer (TRL...) records are neither.
    """
    # TODO 6: spark.read.text(path); drop lines starting with "HDR" or "TRL";
    #   keep lines whose F.length is FIXED_WIDTH. For each (name, start, width)
    #   in FIXED_LAYOUT take F.trim(F.substring("value", start, width)).
    #   opened: F.try_to_date(..., "yyyyMMdd"); sales: sales_cents
    #   .try_cast("decimal(12,0)") / 100, cast to "decimal(12,2)".
    #   rejects: the other data lines, as a column named "line".
    return None


def write_report(df, out_dir):
    """Write `df` as ONE CSV file that Python's csv module reads back exactly.

    Returns the path of the part file.
    """
    # TODO 7: df.coalesce(1).write.mode("overwrite") with header (true),
    #   escape ('"'), ignoreLeadingWhiteSpace and ignoreTrailingWhiteSpace
    #   (false: the CSV writer trims values by default), then .csv(out_dir).
    #   Return the one file matching os.path.join(out_dir, "part-*.csv").
    return None


# ---- Test harness ----
if __name__ == "__main__":
    import csv
    import datetime as dt
    import glob
    import os
    import shutil
    import tempfile
    from decimal import Decimal

    spark = (SparkSession.builder
             .appName("CsvAndDelimited")
             .master("local[*]")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    DIR = "data/messy/delimited"
    tmp = tempfile.mkdtemp(prefix="csv_")
    try:
        # The defaults get products.csv wrong: line breaks split records and
        # doubled quotes are kept as-is. Checked so a change in Spark shows up.
        naive = spark.read.option("header", True).csv(f"{DIR}/products.csv")
        assert naive.count() == 17, "expected the default reader to split the two multi-line records"
        assert naive.filter(F.col("description").contains('""')).count() > 0, "expected raw doubled quotes"

        # ---- products
        products = read_products(spark, f"{DIR}/products.csv")
        assert products is not None, "read_products() returned None: complete TODO 1"
        products = products.cache()
        with open(f"{DIR}/products.csv", newline="", encoding="utf-8") as f:
            ref = list(csv.DictReader(f))   # Python's csv module reads RFC 4180 correctly
        n = products.count()
        assert n == len(ref) == 15, (
            f"Expected 15 products, got {n}. Two descriptions contain line breaks inside quotes: "
            "set multiLine to true")
        types = dict(products.dtypes)
        assert types["sku"] == "string" and types["price"] == "decimal(10,2)", (
            f"Use PRODUCT_SCHEMA (sku STRING keeps leading zeros); got {types}")
        assert types["in_stock"] == "boolean", f"in_stock should become a boolean (try_cast), got {types['in_stock']}"
        got = {r["sku"]: r for r in products.collect()}
        assert set(got) == {r["sku"] for r in ref}, f"SKUs differ from the file (leading zeros?): {sorted(got)}"
        assert got["00042"]["description"] == "Boils 1.7 L.\nAuto shut-off.", (
            f"00042's description is {got['00042']['description']!r}: keep the line break (multiLine)")
        assert got["00107"]["description"] == 'The "classic" mug', (
            f"00107's description is {got['00107']['description']!r}: set escape to '\"' so \"\" becomes one quote")
        assert got["00230"]["description"] is None, "An empty unquoted field should be NULL"
        assert got["00231"]["description"] == "", (
            f"00231's quoted empty field should stay an empty string, got {got['00231']['description']!r}. "
            "With nullValue='NA' only NA (and unquoted empty fields) become NULL")
        assert got["00231"]["in_stock"] is None and got["10007"]["price"] is None, "NA should be NULL"
        assert got["00042"]["in_stock"] is True and got["00107"]["in_stock"] is False, "yes/no -> true/false"
        for r in ref:
            want = None if r["price"] == "NA" else Decimal(r["price"])
            assert got[r["sku"]]["price"] == want, f"{r['sku']}: price {got[r['sku']]['price']} != {want}"

        # ---- orders_eu
        orders = read_orders_eu(spark, f"{DIR}/orders_eu.csv")
        assert orders is not None, "read_orders_eu() returned None: complete TODO 2"
        assert orders.columns[:7] == ["order_id", "sku", "customer", "amount", "order_date", "note",
                                      "_corrupt_record"], f"orders columns: {orders.columns}"
        orders = orders.cache()
        rows = orders.collect()
        assert len(rows) == 18, f"Expected 18 orders (comment lines skipped), got {len(rows)}"
        bad = sorted(r["order_id"] for r in rows if r["_corrupt_record"] is not None)
        assert bad == [1003, 1006], (
            f"Rows with a bad date (31.09.2026) or amount (abc) should have _corrupt_record set; got {bad}")
        expected_total = Decimal(0)
        for line in open(f"{DIR}/orders_eu.csv", encoding="utf-8-sig"):
            if line.startswith(("#", "order_id")):
                continue
            amount = line.split(";")[3]
            if line.split(";")[0] in ("1003", "1006"):
                continue
            expected_total += Decimal(amount.replace(".", "").replace(",", "."))
        good = [r for r in rows if r["_corrupt_record"] is None]
        total = sum(r["amount"] for r in good)
        assert total == expected_total, (
            f"Sum of amounts is {total}, expected {expected_total}. '1.234,50' must read as 1234.50: "
            "set locale to de-DE (it applies to DECIMAL columns)")
        r1001 = next(r for r in rows if r["order_id"] == 1001)
        assert r1001["order_date"] == dt.date(2026, 10, 1) and r1001["note"] == "Lieferung; Tor 3", (
            f"Order 1001 read as {r1001}: dateFormat dd.MM.yyyy, and the quoted ';' stays in the note")
        assert all(r["file"] == "orders_eu.csv" for r in rows), "Add file from _metadata.file_name"

        # ---- legacy
        legacy = read_legacy(spark, f"{DIR}/legacy_latin1.tsv")
        assert legacy is not None, "read_legacy() returned None: complete TODO 3"
        assert legacy.columns == LEGACY_NAMES, f"legacy columns {legacy.columns}: rename them all with toDF"
        lg = {r["id"]: r for r in legacy.collect()}
        assert lg["1"]["first_name"] == "Zoë" and lg["3"]["city"] == "Besançon", (
            f"Accents are broken ({lg['1']['first_name']!r}, {lg['3']['city']!r}): read with encoding ISO-8859-1")
        assert lg["2"]["notes"] == "señor" and not lg["2"]["notes"].endswith("\r"), "Windows line endings leaked"

        # ---- sales
        result = read_sales(spark, f"{DIR}/sales")
        assert result is not None, "read_sales() returned None: complete TODOs 4 and 5"
        sales, rejects = result
        assert sales is not None and rejects is not None, "read_sales() must return (sales, rejects)"
        assert sales.columns == ["id", "amount", "day", "currency", "file"], f"sales columns: {sales.columns}"
        s = {r["id"]: r for r in sales.collect()}
        rj = sorted((r["file"], r["reason"]) for r in rejects.collect())
        assert len(s) + len(rj) == 13, f"Rows went missing: {len(s)} sales + {len(rj)} rejects != 13"
        assert rj == [("sales_2026-10-01.csv", "wrong_column_count"), ("sales_2026-10-02.csv", "bad_value")], (
            f"Rejects should be the short row on day 1 and the n/a amount on day 2; got {rj}")
        assert s[6]["amount"] == Decimal("12.00") and s[6]["day"] == dt.date(2026, 10, 2), (
            f"Day 2 has its columns in another order; row 6 read as {s[6]}. Match columns by name")
        assert s[10]["currency"] == "EUR" and s[1]["currency"] is None, "currency exists from day 3 only"
        assert sum(r["amount"] for r in s.values()) == Decimal("98.10"), "Sum of sales amounts is wrong"

        # ---- fixed width
        result = read_fixed(spark, f"{DIR}/stores_fixed.txt")
        assert result is not None, "read_fixed() returned None: complete TODO 6"
        stores, bad_lines = result
        st = {r["store_id"]: r for r in stores.collect()}
        trailer = [l for l in open(f"{DIR}/stores_fixed.txt", encoding="utf-8") if l.startswith("TRL")][0]
        assert len(st) == int(trailer[3:]), f"The trailer says {int(trailer[3:])} stores, you have {len(st)}"
        assert st["0002"]["name"] == "Le Petit Marché" and st["0003"]["city"] == "Hà Nội", (
            f"Names and cities should be trimmed text: {st.get('0002')}, {st.get('0003')}")
        assert st["0001"]["opened"] == dt.date(2019, 3, 1), f"opened: {st['0001']['opened']}"
        assert st["0001"]["sales"] == Decimal("12500.50") and st["0004"]["sales"] == Decimal("0.00"), (
            f"sales is the cents field divided by 100: {st['0001']['sales']}, {st['0004']['sales']}")
        assert [r["line"] for r in bad_lines.collect()] == ["0005Broken Line"], "The truncated line is a reject"

        # ---- write_report
        tricky = spark.createDataFrame([
            (1, "plain", "a,b"),
            (2, 'say "hi"', "  padded  "),
            (3, "two\nlines", ""),
            (4, None, "Zoë; Hà Nội"),
        ], "id INT, text STRING, more STRING")
        out = os.path.join(tmp, "report")
        part = write_report(tricky, out)
        assert part is not None, (
            "write_report() should return the path of exactly one part-*.csv file: complete TODO 7 (coalesce(1))")
        assert len(glob.glob(os.path.join(out, "part-*"))) == 1, "Expected one part file"
        with open(part, newline="", encoding="utf-8") as f:
            back = list(csv.reader(f))
        want = [["id", "text", "more"], ["1", "plain", "a,b"], ["2", 'say "hi"', "  padded  "],
                ["3", "two\nlines", ""], ["4", "", "Zoë; Hà Nội"]]
        assert back == want, (
            f"Python's csv module read back {back}. Write with escape='\"' and without trimming "
            "(ignoreLeadingWhiteSpace/ignoreTrailingWhiteSpace false)")

        print("Products:")
        products.show(5, truncate=False)
        print("European orders (bad rows keep their raw text):")
        orders.filter(F.col("_corrupt_record").isNotNull()).select("order_id", "_corrupt_record").show(truncate=False)
        print("Legacy file:")
        legacy.show()
        print("Sales across three layouts:")
        sales.orderBy("id").show()
        rejects.show(truncate=False)
        print("Fixed-width stores:")
        stores.show()
        print("Report file:")
        print(open(part, encoding="utf-8").read())
        print("All tests passed!")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        spark.stop()
