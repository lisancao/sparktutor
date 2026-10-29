"""
Columns and Expressions: Cleaning Values - Exercise

A customer export where every column is text and nothing is consistent:
padded and badly cased names, non-breaking spaces, "N/A" for missing,
dates in six formats, money with dollar signs and thousands separators,
yes/no/Y/1 booleans, impossible ages and a dozen spellings of three
countries. Turn it into typed columns, and say for every row what was
wrong with it instead of silently dropping or guessing.
"""

from pyspark.sql import SparkSession, functions as F

# Strings that mean "no value" in this export (compared after tidying and
# upper-casing, so "n/a" and " N/A " count too)
NULL_TOKENS = ["", "N/A", "NA", "NULL", "NONE", "-"]

# Formats seen in signup_date, tried in this order after the ISO default.
# The source system documents slash dates as day/month/year.
DATE_PATTERNS = ["yyyy/MM/dd", "dd/MM/yyyy", "d MMM yyyy", "MMMM d, yyyy", "yyyyMMdd"]

EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$"

# The order reasons appear in reject_reason
REASONS = ["missing_name", "bad_email", "bad_phone", "bad_country",
           "bad_date", "bad_ltv", "bad_newsletter", "bad_age"]


def tidy(c):
    """Collapse every run of whitespace (including the non-breaking space
    U+00A0) to one space, trim the ends, and turn null markers into NULL."""
    # TODO 1: squeeze runs of [\s\u00a0] into one space with F.regexp_replace,
    #   then F.trim the result. Return F.when(<upper-cased value>.isin(NULL_TOKENS),
    #   None).otherwise(<the squeezed value>).
    return None


def parse_date(c):
    """The first format that parses wins; NULL if none does."""
    # TODO 2: F.coalesce of F.try_to_date(c) (the ISO default, which also
    #   accepts '2025-03-09T14:30:00') and F.try_to_date(c, p) for every p in
    #   DATE_PATTERNS
    return None


def parse_money(c):
    """'$1,234.50', ' $7.25 ', '-$5.00', '1234.5' -> DECIMAL(12,2); NULL if not a number."""
    # TODO 3: remove "$", "," and whitespace with F.regexp_replace, then
    #   .try_cast("decimal(12,2)") (a plain cast fails the query on "abc")
    return None


def clean_customers(raw, countries):
    """Typed, standardized customers plus a reject_reason column.

    raw:       the CSV read with every column as a string
    countries: the mapping table (raw STRING, code STRING)

    Returns customer_id, name, email, phone, country, signup_date,
    lifetime_value, newsletter, age, city, reject_reason. A value that is
    present but invalid becomes NULL in its typed column and adds its
    reason; a missing value is just NULL (except the name, which is
    required).
    """
    # TODO 4: tidy every raw column once, keeping the raw names:
    #   t = raw.withColumns({c: tidy(F.col(c)) for c in raw.columns})
    t = None

    # TODO 5: add typed candidates to `t` with one withColumns call:
    #   customer_id: upper-cased
    #   name:        F.initcap of full_name
    #   email_clean: lower-cased email; email_ok: email_clean.rlike(EMAIL_RE)
    #   phone_clean: only the digits of phone (regexp_replace "[^0-9]" with ""),
    #                minus a leading "1" when there are 11 digits;
    #   phone_ok:    phone_clean.rlike("^[0-9]{10}$")
    #   country_key: upper-cased country without dots ("U.S." -> "US")
    #   signup:      parse_date(signup_date); ltv: parse_money(lifetime_value)
    #   news:        newsletter.try_cast("boolean") (yes/no/y/n/1/0/true/false)
    #   age_int:     age.try_cast("int"); age_ok: age_int.between(0, 120)
    typed = None

    # TODO 6: left-join the mapping table on country_key == raw, broadcasting
    #   it (F.broadcast(countries)) because it is tiny. Its "code" column is the
    #   standardized country.
    mapped = None

    # TODO 7: build reject_reason: for each name in REASONS, a condition that is
    #   true when the tidied raw value is present (not NULL) but its typed
    #   candidate failed (bad_country: code is NULL; bad_age: age_ok is not true;
    #   missing_name: name is NULL). Combine F.when(cond, F.lit(name)) for all of
    #   them with F.concat_ws(",", ...) (it skips NULLs) and turn "" into NULL
    #   with F.nullif. Then select the output columns in the docstring's order,
    #   with invalid email, phone and age shown as NULL.
    return None


def city_counts(clean):
    """Customers per city, treating case, accents and padding as the same city."""
    # TODO 8: group by F.collate("city", "UNICODE_CI_AI") aliased "city",
    #   count, and order by count descending
    return None


# ---- Test harness ----
if __name__ == "__main__":
    import csv
    import datetime as dt
    import logging
    import unicodedata
    from decimal import Decimal

    from pyspark.errors import PySparkException

    spark = (SparkSession.builder
             .appName("CleaningValues")
             .master("local[*]")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    RAW = "data/messy/cleaning/customers_raw.csv"
    CODES = "data/messy/cleaning/country_codes.csv"
    try:
        # Every column as a string ("CSV and Delimited Files" covers the options)
        raw = spark.read.option("header", True).csv(RAW)
        countries = spark.read.option("header", True).csv(CODES)

        # Why try_cast: under ANSI mode (the default since 4.0) a plain cast
        # fails the whole query on the first bad value.
        # Keep the expected failure quiet: the JVM log and PySpark's own
        # DataFrameQueryContextLogger would both print it
        spark.sparkContext.setLogLevel("OFF")
        logging.getLogger("DataFrameQueryContextLogger").setLevel(logging.CRITICAL)
        try:
            raw.select(F.col("age").cast("int")).collect()
            raise AssertionError("expected cast('int') on the raw ages to fail under ANSI mode")
        except PySparkException as e:
            assert e.getCondition() == "CAST_INVALID_INPUT", f"unexpected error {e.getCondition()}"
            print("A plain cast of the raw ages fails as expected:", e.getCondition())
        finally:
            spark.sparkContext.setLogLevel("ERROR")
            logging.getLogger("DataFrameQueryContextLogger").setLevel(logging.NOTSET)

        # ---- tidy
        samples = ["  ana   maria  ", "Zoë\u00a0Tremblay", "José\tGarcía", "N/A", "n/a", " ", "-", "\u00a0 ", None, "NAN"]
        probe = spark.createDataFrame([(s,) for s in samples], "s STRING")
        assert tidy(F.col("s")) is not None, "tidy() returned None: complete TODO 1"
        got = [r[0] for r in probe.select(tidy(F.col("s"))).collect()]
        want = ["ana maria", "Zoë Tremblay", "José García", None, None, None, None, None, None, "NAN"]
        for s, g, w in zip(samples, got, want):
            assert g == w, (f"tidy({s!r}) gave {g!r}, expected {w!r}. Collapse [\\s\\u00a0]+ to one space, "
                            "trim, then NULL when the upper-cased value is in NULL_TOKENS")

        # ---- parse_date
        dates = {"2025-03-04": dt.date(2025, 3, 4), "2025/03/05": dt.date(2025, 3, 5),
                 "05/03/2025": dt.date(2025, 3, 5), "4 Mar 2025": dt.date(2025, 3, 4),
                 "March 4, 2025": dt.date(2025, 3, 4), "20250306": dt.date(2025, 3, 6),
                 "2025-03-09T14:30:00": dt.date(2025, 3, 9),
                 "2025-02-30": None, "unknown": None}
        assert parse_date(F.col("s")) is not None, "parse_date() returned None: complete TODO 2"
        probe = spark.createDataFrame([(s,) for s in dates], "s STRING")
        for s, d in probe.select("s", parse_date(F.col("s")).alias("d")).collect():
            assert d == dates[s], (f"parse_date({s!r}) gave {d}, expected {dates[s]}. Coalesce "
                                   "try_to_date(c) with try_to_date(c, p) for every p in DATE_PATTERNS")

        # ---- parse_money
        money = {"$1,234.50": Decimal("1234.50"), " $7.25 ": Decimal("7.25"), "-$5.00": Decimal("-5.00"),
                 "1234.5": Decimal("1234.50"), "1,000": Decimal("1000.00"), "abc": None}
        assert parse_money(F.col("s")) is not None, "parse_money() returned None: complete TODO 3"
        probe = spark.createDataFrame([(s,) for s in money], "s STRING")
        mt = probe.select(parse_money(F.col("s")).alias("m")).dtypes[0][1]
        assert mt == "decimal(12,2)", f"parse_money should return decimal(12,2), got {mt}"
        for s, m in probe.select("s", parse_money(F.col("s"))).collect():
            assert m == money[s], f"parse_money({s!r}) gave {m}, expected {money[s]}"

        # ---- clean_customers
        clean = clean_customers(raw, countries)
        assert clean is not None, "clean_customers() returned None: complete TODOs 4 to 7"
        cols = ["customer_id", "name", "email", "phone", "country", "signup_date",
                "lifetime_value", "newsletter", "age", "city", "reject_reason"]
        assert clean.columns == cols, f"clean_customers columns should be {cols}, got {clean.columns}"
        types = dict(clean.dtypes)
        want_types = {"signup_date": "date", "lifetime_value": "decimal(12,2)",
                      "newsletter": "boolean", "age": "int", "reject_reason": "string"}
        for c, t in want_types.items():
            assert types[c] == t, f"column {c} should be {t}, got {types[c]}"
        clean = clean.cache()
        n_raw, n_clean = raw.count(), clean.count()
        assert n_clean == n_raw == 40, f"Rows went missing or were duplicated: {n_raw} raw, {n_clean} clean"

        rows = {r["customer_id"]: r for r in clean.collect()}
        D = Decimal
        expected = {
            "C001": ("Ana Maria Nguyen", "ana.nguyen@example.com", "4165550199", "CA",
                     dt.date(2025, 3, 4), D("1234.50"), True, 34, "Montréal", None),
            "C002": ("Binh Tran", "binh@example.com", "4165550123", "US",
                     dt.date(2025, 3, 5), D("1234.50"), True, 41, "MONTREAL", None),
            "C003": ("Zoë Tremblay", None, "4165550147", "US",
                     dt.date(2025, 3, 5), D("12.00"), False, None, "montreal", None),
            "C004": ("José García", None, None, "VN",
                     dt.date(2025, 3, 4), D("-5.00"), False, None, "Hà Nội", "bad_email,bad_phone,bad_age"),
            "C005": ("Nguyễn Thị Hà", None, None, "VN",
                     dt.date(2025, 3, 4), None, None, 29, "Ha Noi", None),
            "C006": ("Emma Smith", None, "4165550188", None, None, None, None, None, "Toronto",
                     "bad_email,bad_country,bad_date,bad_ltv,bad_newsletter,bad_age"),
            "C007": ("Dev Patel", "dev@example.ca", "4165550177", "CA",
                     dt.date(2025, 3, 6), D("1000.00"), True, None, "toronto", "bad_age"),
            "C008": ("Mona Lee", "mona@example.com", None, "FR",
                     None, D("7.25"), False, 52, "Paris", "bad_date"),
            "C009": ("Omar Haddad", "omar@example.com", "4165550101", "US",
                     dt.date(2025, 3, 9), D("0.99"), False, 61, "Toronto", None),
            "C010": (None, "ghost@example.com", "4165550100", "CA",
                     dt.date(2025, 3, 10), D("5.00"), True, 40, "Paris", "missing_name"),
        }
        assert set(rows) == {f"C{i:03d}" for i in range(1, 41)}, (
            f"customer_id should be trimmed and upper-cased (C001 to C040); got {sorted(rows)[:5]}...")
        for cid, want in expected.items():
            got = tuple(rows[cid][c] for c in cols[1:])
            for c, g, w in zip(cols[1:], got, want):
                assert g == w, f"{cid}.{c} is {g!r}, expected {w!r}"

        filler_rejects = [(cid, r["reject_reason"]) for cid, r in rows.items()
                          if cid not in expected and r["reject_reason"] is not None]
        assert not filler_rejects, f"These rows should be clean but were rejected: {filler_rejects}"
        # Cross-check the filler rows against the raw file with plain Python
        with open(RAW, encoding="utf-8") as f:
            raw_rows = {r["customer_id"].strip().upper(): r for r in csv.DictReader(f)}
        for cid, r in rows.items():
            if cid in expected:
                continue
            src = raw_rows[cid]
            assert r["country"] in {"CA", "US", "VN", "FR"}, f"{cid}: country {src['country']!r} -> {r['country']}"
            assert r["signup_date"] is not None, f"{cid}: date {src['signup_date']!r} did not parse"
            if src["lifetime_value"] != "N/A":
                assert r["lifetime_value"] is not None, f"{cid}: money {src['lifetime_value']!r} did not parse"
            assert r["newsletter"] is not None, f"{cid}: newsletter {src['newsletter']!r} did not parse"
            if src["phone"] != "n/a":
                assert r["phone"] and len(r["phone"]) == 10, f"{cid}: phone {src['phone']!r} -> {r['phone']}"
            assert r["name"] == " ".join(src["full_name"].split()).title(), f"{cid}: name {r['name']!r}"

        # ---- city_counts
        counts = city_counts(clean)
        assert counts is not None, "city_counts() returned None: complete TODO 8"

        def key(s):
            return "".join(ch for ch in unicodedata.normalize("NFKD", s.strip().lower())
                           if not unicodedata.combining(ch))
        want_counts = {}
        for r in rows.values():
            want_counts[key(r["city"])] = want_counts.get(key(r["city"]), 0) + 1
        got_counts = {key(r["city"]): r["count"] for r in counts.collect()}
        assert got_counts == want_counts, (
            f"city_counts should group {want_counts}, got {got_counts}. Group by "
            "F.collate('city', 'UNICODE_CI_AI') after tidy() has trimmed the padding")

        print("Clean customers (planted rows):")
        clean.filter(F.col("customer_id") <= "C010").orderBy("customer_id").show(truncate=False)
        print("Rejected rows:")
        clean.filter(F.col("reject_reason").isNotNull()).select("customer_id", "reject_reason").show(truncate=False)
        print("Customers per city (case and accent insensitive):")
        counts.show()
        print("All tests passed!")
    finally:
        spark.stop()
