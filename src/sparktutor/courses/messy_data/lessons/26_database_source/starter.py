"""
A Database Source: Partitions and Pushdown with SQLite - Exercise

A Python data source over a SQLite table. It maps SQLite's declared column
types to Spark types, splits the table into key ranges the way Spark's JDBC
source does, and pushes filters into each range's SQL WHERE clause with
parameters. Every query a task runs is written to an audit log, so the tests
can see exactly what the database was asked.
"""

import datetime
import decimal
import json
import os
import pathlib
import re
import sqlite3
import uuid

from pyspark.sql import SparkSession, functions as sf
from pyspark.sql.datasource import (
    DataSource, DataSourceReader, EqualTo, GreaterThan, GreaterThanOrEqual, In,
    InputPartition, IsNotNull, IsNull, LessThan, LessThanOrEqual, StringStartsWith,
)


# ---- SQLite helpers (written for you) ----

def connect_ro(path):
    """Open a SQLite file read-only. Each caller opens its own connection and closes it."""
    return sqlite3.connect(pathlib.Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def quote_ident(name):
    """Quote a table or column name for SQL. Names cannot be passed as ? parameters."""
    return '"' + name.replace('"', '""') + '"'


def affinity(declared):
    """SQLite's type affinity for a declared column type (rules from sqlite.org/datatype3.html)."""
    t = (declared or "").upper()
    if "INT" in t:
        return "INTEGER"
    if "CHAR" in t or "CLOB" in t or "TEXT" in t:
        return "TEXT"
    if "BLOB" in t or t == "":
        return "BLOB"
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return "REAL"
    return "NUMERIC"


def table_columns(conn, table):
    """[(name, declared type)] for a table that must exist (checked against sqlite_master)."""
    found = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    if found is None:
        raise ValueError(f"No table named {table!r} in the database")
    return [(row[1], row[2]) for row in conn.execute(f"PRAGMA table_info({quote_ident(table)})")]


def to_spark_value(value, spark_type):
    """Convert what sqlite3 returned to a Python value for the Spark type, or None if it does not fit."""
    if value is None:
        return None
    if spark_type == "bigint":
        return value if isinstance(value, int) else None
    if spark_type == "double":
        return float(value) if isinstance(value, (int, float)) else None
    if spark_type.startswith("decimal"):
        if not isinstance(value, (int, float)):
            return None
        precision, scale = map(int, re.findall(r"\d+", spark_type))
        d = decimal.Decimal(str(value)).quantize(decimal.Decimal(1).scaleb(-scale))
        return d if len(d.as_tuple().digits) <= precision else None
    if spark_type == "string":
        return str(value) if isinstance(value, (str, int, float)) else None
    if spark_type == "boolean":
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            return {"true": True, "yes": True, "y": True, "1": True,
                    "false": False, "no": False, "n": False, "0": False}.get(value.strip().lower())
        return None
    if spark_type == "timestamp":
        if isinstance(value, (int, float)):
            return datetime.datetime.fromtimestamp(value, datetime.timezone.utc)
        if isinstance(value, str):
            try:
                ts = datetime.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                return None
            return ts if ts.tzinfo else ts.replace(tzinfo=datetime.timezone.utc)
        return None
    return None


def guard(column, spark_type):
    """SQL that is true exactly when to_spark_value keeps the column's value (not NULL)."""
    q = quote_ident(column)
    if spark_type == "bigint":
        return f"typeof({q}) = 'integer'"
    if spark_type == "double" or spark_type.startswith("decimal"):
        return f"typeof({q}) IN ('integer', 'real')"
    return f"typeof({q}) = 'text'"


def quantile_bounds(conn, table, column, n):
    """n - 1 split points that put about the same number of rows in each range."""
    q, t = quote_ident(column), quote_ident(table)
    count = conn.execute(f"SELECT count({q}) FROM {t}").fetchone()[0]
    points = []
    for i in range(1, n):
        row = conn.execute(f"SELECT {q} FROM {t} WHERE {q} IS NOT NULL ORDER BY {q} "
                           f"LIMIT 1 OFFSET ?", (count * i // n,)).fetchone()
        if row and (not points or row[0] > points[-1]):
            points.append(row[0])
    return points


# ---- Part 1: SQLite declared types to Spark types ----

def spark_type(declared):
    """The Spark type (DDL string) for a SQLite declared type, following its affinity."""
    # TODO: start from aff = affinity(declared) and t = (declared or "").upper()
    #   INTEGER -> "bigint"; TEXT or BLOB -> "string"; REAL -> "double"
    #   NUMERIC: DECIMAL(p,s) or NUMERIC(p,s) -> f"decimal({p},{s})" (spaces allowed inside the
    #            parentheses; re.match is handy), a name containing BOOL -> "boolean",
    #            DATE or TIME -> "timestamp", anything else -> "double"
    return None


# ---- Part 2: key ranges, like Spark's JDBC partitionColumn ----

def range_partitions(column, split_points):
    """One (where_sql, params) per range. The first range also takes NULL keys, the last is open."""
    q = quote_ident(column)
    # TODO: with no split points, return [("1 = 1", [])]
    # Otherwise, for split points p1 < p2 < ... < pk, return k + 1 ranges:
    #   (f"({q} < ? OR {q} IS NULL)", [p1])
    #   (f"({q} >= ? AND {q} < ?)", [p1, p2]), ... one per pair of neighbours
    #   (f"{q} >= ?", [pk])
    # The bounds always go into params, never into the SQL text.
    return []


def stride_points(lower, upper, n):
    """Evenly spaced split points between lower and upper (the JDBC source's idea)."""
    if n <= 1 or upper <= lower:
        return []
    points = sorted({lower + (upper - lower) * i // n for i in range(1, n)})
    return [p for p in points if lower < p < upper] or []


# ---- Part 3: one pushed filter to SQL ----

COMPARISONS = {EqualTo: "=", GreaterThan: ">", GreaterThanOrEqual: ">=",
               LessThan: "<", LessThanOrEqual: "<="}


def compile_filter(f, types, pushable):
    """(sql, params) that selects exactly the rows Spark would keep for f, or None to leave f to Spark.

    types: {column: spark type}; pushable: the columns whose values SQLite stores reliably
    (INTEGER, TEXT, REAL affinity and decimals).
    """
    attribute = getattr(f, "attribute", None)  # Not wraps another filter and has no attribute
    if attribute is None or len(attribute) != 1 or attribute[0] not in pushable:
        return None
    column = attribute[0]
    t = types[column]
    q, g = quote_ident(column), guard(column, t)

    def param(v):
        # sqlite3 cannot bind Decimal; the column stores REAL anyway
        return float(v) if isinstance(v, decimal.Decimal) else v

    # TODO: return (sql, params) for these filter types, and None for anything else:
    #   EqualTo and the four comparisons (see COMPARISONS):
    #       (f"({g} AND {q} <op> ?)", [param(f.value)])
    #   In: drop None from f.value; no values left -> ("0", []);
    #       otherwise (f"({g} AND {q} IN (?, ?, ...))", values) with one ? per value
    #   IsNull: every row Spark sees as NULL, including values the guard rejects:
    #       (f"(NOT ({g}) OR {q} IS NULL)", [])
    #   IsNotNull: (f"({g})", [])
    #   StringStartsWith on a "string" column: compare a prefix, not LIKE:
    #       (f"({g} AND substr({q}, 1, ?) = ?)", [len(f.value), f.value])
    return None


# ---- The data source ----

class SqlitePartition(InputPartition):
    def __init__(self, index, where, params, snapshot):
        self.index = index
        self.where = where
        self.params = params
        self.snapshot = snapshot


class SqliteDataSource(DataSource):
    """format("sqlite"): options path, table (required); partitionColumn, lowerBound, upperBound,
    numPartitions (default 1), bounds ("range" or "quantile"), audit_dir, pushdown ("true")."""

    @classmethod
    def name(cls):
        return "sqlite"

    def schema(self):
        conn = connect_ro(self.options["path"])
        try:
            cols = table_columns(conn, self.options["table"])
        finally:
            conn.close()
        return ", ".join(f"`{n}` {spark_type(d)}" for n, d in cols)

    def reader(self, schema):
        return SqliteReader(self.options, schema)


class SqliteReader(DataSourceReader):
    def __init__(self, options, schema):
        self.path = options["path"]
        self.table = options["table"]
        self.columns = [f.name for f in schema.fields]
        self.types = {f.name: f.dataType.simpleString() for f in schema.fields}
        conn = connect_ro(self.path)  # short-lived, on the driver; never kept on self
        try:
            declared = dict(table_columns(conn, self.table))
        finally:
            conn.close()
        self.pushable = {c for c in self.columns
                         if affinity(declared.get(c)) in ("INTEGER", "TEXT", "REAL")
                         or self.types[c].startswith("decimal")}
        self.key = options.get("partitionColumn")
        self.lower = options.get("lowerBound")
        self.upper = options.get("upperBound")
        self.n = int(options.get("numPartitions", 1))
        self.bounds = options.get("bounds", "range")
        self.audit_dir = options.get("audit_dir")
        self.push = options.get("pushdown", "true").lower() == "true"
        self.pushed = []   # (sql, params) for every filter this reader took over

    # ---- Part 4: take over the filters SQLite can apply exactly ----
    def pushFilters(self, filters):
        # TODO: for each filter f, compiled = compile_filter(f, self.types, self.pushable)
        #   (or None when self.push is False). If compiled is None, yield f back to Spark;
        #   otherwise append it to self.pushed and do not yield f.
        yield from filters


    def partitions(self):
        conn = connect_ro(self.path)
        try:
            # Snapshot mark: rows inserted after planning are not read by any task
            snapshot = conn.execute(f"SELECT max(rowid) FROM {quote_ident(self.table)}").fetchone()[0]
            if not self.key or self.n <= 1:
                ranges = [("1 = 1", [])]
            elif self.bounds == "quantile":
                ranges = range_partitions(self.key, quantile_bounds(conn, self.table, self.key, self.n))
            else:
                if self.lower is None or self.upper is None:
                    lo, hi = conn.execute(f"SELECT min({quote_ident(self.key)}), max({quote_ident(self.key)}) "
                                          f"FROM {quote_ident(self.table)}").fetchone()
                else:
                    lo, hi = int(self.lower), int(self.upper)
                ranges = range_partitions(self.key, stride_points(lo, hi, self.n))
        finally:
            conn.close()
        return [SqlitePartition(i, w, p, snapshot or 0) for i, (w, p) in enumerate(ranges)]

    # ---- Part 5: the query one task runs ----
    def build_query(self, partition):
        """(sql, params) for one partition: its range, the snapshot mark and every pushed filter."""
        cols = ", ".join(quote_ident(c) for c in self.columns)
        # TODO: conditions are partition.where, then "rowid <= ?", then the SQL of every pushed
        # filter, joined with " AND ". params are partition.params, then partition.snapshot,
        # then the params of every pushed filter, in the same order as the ? marks.
        sql = f"SELECT {cols} FROM {quote_ident(self.table)} WHERE " + partition.where
        params = list(partition.params)
        return sql, params


    def read(self, partition):
        sql, params = self.build_query(partition)
        if self.audit_dir:
            with open(os.path.join(self.audit_dir, f"{uuid.uuid4().hex}.jsonl"), "w") as log:
                log.write(json.dumps({"partition": partition.index, "sql": sql, "params": params}) + "\n")
        conn = connect_ro(self.path)  # opened in the task, where it is used
        try:
            cursor = conn.execute(sql, params)
            while True:
                rows = cursor.fetchmany(500)
                if not rows:
                    break
                for row in rows:
                    yield tuple(to_spark_value(v, self.types[c]) for v, c in zip(row, self.columns))
        finally:
            conn.close()


# ---- Sample database (made by the harness in a temporary folder) ----

def make_shop_db(path):
    """A messy orders table: declared types SQLite does not enforce, and a few legacy ids far away."""
    import random
    rng = random.Random(26)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE orders (
            order_id  INTEGER PRIMARY KEY,
            customer  VARCHAR(40),
            status    TEXT,
            amount    DECIMAL(10,2),
            qty       INT,
            placed_at DATETIME,
            gift      BOOLEAN,
            note
        )""")
    customers = ["Ana", "Bao", "Chloe", "Dev", "Emeka", "Farah", "Goran", "Hana"]
    statuses = ["shipped"] * 5 + ["pending"] * 3 + ["cancelled", "Shipped"]
    rows = []
    for i in list(range(1, 1201)) + list(range(100001, 100007)):
        r = rng.random()
        amount = ("N/A" if r < 0.03 else "" if r < 0.05 else "12,50" if r < 0.06
                  else None if r < 0.08 else round(rng.uniform(5, 250), 2))
        q = rng.random()
        qty = "two" if q < 0.02 else str(rng.randint(1, 4)) if q < 0.10 else 2.5 if q < 0.11 \
            else rng.randint(1, 4)
        day = datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(hours=7 * i % 1400)
        p = rng.random()
        placed = (int(day.timestamp()) if p < 0.1 else day.strftime("%Y-%m-%dT%H:%M:%SZ") if p < 0.3
                  else day.strftime("%Y-%m-%d %H:%M:%S"))
        gift = rng.choice([0, 1, 0, "yes", "no", None])
        note = rng.choice([None, None, None, "leave at door", 42, "fragile"])
        rows.append((i, rng.choice(customers), rng.choice(statuses), amount, qty, placed, gift, note))
    rows.append((1201, "x' OR '1'='1", "pending", 9.99, 1, "2026-10-01 00:00:00", 0, None))
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


# ---- Test harness ----
if __name__ == "__main__":
    import contextlib
    import io
    import shutil
    import tempfile

    from pyspark.sql.datasource import Not

    work = tempfile.mkdtemp(prefix="sqlite_source_")
    db = os.path.join(work, "shop.db")
    make_shop_db(db)

    # 1. Type mapping, without Spark
    expected_types = {
        "INTEGER": "bigint", "INT": "bigint", "BIGINT": "bigint", "VARCHAR(40)": "string",
        "TEXT": "string", "": "string", "BLOB": "string", "REAL": "double", "DOUBLE PRECISION": "double",
        "FLOAT": "double", "DECIMAL(10,2)": "decimal(10,2)", "NUMERIC(5, 1)": "decimal(5,1)",
        "NUMERIC": "double", "BOOLEAN": "boolean", "DATETIME": "timestamp", "DATE": "timestamp",
        "FLOATING POINT": "bigint",
    }
    for declared, want in expected_types.items():
        got = spark_type(declared)
        assert got == want, (
            f"spark_type({declared!r}) should be {want!r}, got {got!r}. Start from affinity(declared): "
            "INTEGER -> bigint, TEXT and BLOB -> string, REAL -> double; for NUMERIC look at the name "
            "(DECIMAL(p,s) or NUMERIC(p,s), BOOL, DATE/TIME, otherwise double)")

    # 2. Key ranges, without Spark
    got = range_partitions("order_id", [301, 601, 901])
    want = [('("order_id" < ? OR "order_id" IS NULL)', [301]),
            ('("order_id" >= ? AND "order_id" < ?)', [301, 601]),
            ('("order_id" >= ? AND "order_id" < ?)', [601, 901]),
            ('"order_id" >= ?', [901])]
    assert got == want, (
        f"range_partitions('order_id', [301, 601, 901]) should be\n  {want}\ngot\n  {got}\n"
        "First range: key < first point OR key IS NULL; middle: >= lo AND < hi; last: >= last point. "
        "Bounds go into params, never into the SQL text")
    assert range_partitions("order_id", []) == [("1 = 1", [])], \
        "With no split points, range_partitions should return a single range [('1 = 1', [])]"

    # 3. Filter compilation, without Spark
    types = {"order_id": "bigint", "customer": "string", "status": "string", "amount": "decimal(10,2)",
             "qty": "bigint", "placed_at": "timestamp", "gift": "boolean", "note": "string"}
    pushable = {"order_id", "customer", "status", "amount", "qty"}
    c = compile_filter(EqualTo(("status",), "shipped"), types, pushable)
    assert c is not None and "?" in c[0] and "shipped" not in c[0] and c[1] == ["shipped"], (
        f"EqualTo(status, 'shipped') should compile to SQL with a ? placeholder and params ['shipped'], "
        f"got {c}. Never put values into the SQL text")
    c = compile_filter(GreaterThan(("amount",), decimal.Decimal("100.00")), types, pushable)
    assert c is not None and "typeof" in c[0] and c[1] == [100.0] and isinstance(c[1][0], float), (
        f"GreaterThan(amount, Decimal('100.00')) should guard with typeof(...) and bind a float, got {c}. "
        "sqlite3 cannot bind Decimal, and without the guard SQLite says 'N/A' > 100 is true")
    c = compile_filter(In(("qty",), [1, None, 2]), types, pushable)
    assert c is not None and c[1] == [1, 2] and c[0].count("?") == 2, (
        f"In(qty, [1, None, 2]) should bind [1, 2] (one ? each, NULL dropped), got {c}")
    c = compile_filter(IsNull(("amount",)), types, pushable)
    assert c is not None and "NOT" in c[0].upper(), (
        f"IsNull(amount) must also match values that become NULL in Spark (like 'N/A'): "
        f"use NOT (guard) OR column IS NULL. Got {c}")
    c = compile_filter(StringStartsWith(("status",), "ship"), types, pushable)
    assert c is not None and "LIKE" not in c[0].upper() and "ship" in c[1], (
        f"StringStartsWith(status, 'ship') should compare a prefix (substr) with params, not LIKE "
        f"(case-insensitive in SQLite). Got {c}")
    for f in [EqualTo(("placed_at",), datetime.datetime(2026, 10, 1)), EqualTo(("note",), "42"),
              Not(EqualTo(("status",), "shipped")), EqualTo(("a", "b"), 1)]:
        assert compile_filter(f, types, pushable) is None, (
            f"compile_filter({f!r}) should return None (leave it to Spark): only single-level "
            "columns in `pushable` and the filter types listed in the exercise are pushed")

    spark = (SparkSession.builder
        .appName("DatabaseSource")
        .master("local[*]")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    def orders(audit=None, **options):
        """A fresh DataFrame over the table for every query (the 4.2.0 plan-reuse trap)."""
        r = spark.read.format("sqlite").option("path", db).option("table", "orders")
        if audit:
            r = r.option("audit_dir", audit)
        for k, v in options.items():
            r = r.option(k, str(v))
        return r.load()

    def audited(df_fn, condition, **options):
        """Rows, audited queries and Spark's remaining Filter lines for one query."""
        audit = tempfile.mkdtemp(prefix="audit_", dir=work)
        df = df_fn(audit, **options).filter(condition)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            df.explain()
        rows = sorted(df.collect(), key=lambda r: r.order_id)
        queries = [json.loads(line) for name in os.listdir(audit) for line in open(os.path.join(audit, name))]
        spark_filters = [l.strip() for l in buf.getvalue().splitlines() if "Filter" in l and "Scan" not in l]
        return rows, queries, spark_filters

    try:
        spark.dataSource.register(SqliteDataSource)

        # 4. Schema from the table definition
        got_schema = orders().schema.simpleString()
        want_schema = ("struct<order_id:bigint,customer:string,status:string,amount:decimal(10,2),"
                       "qty:bigint,placed_at:timestamp,gift:boolean,note:string>")
        assert got_schema == want_schema, f"Schema should be {want_schema}, got {got_schema}"

        # 5. The 4.2.0 flag: a reader with pushFilters fails every query while it is off
        spark.conf.set("spark.sql.python.filterPushdown.enabled", "false")
        try:
            orders().count()
            raise AssertionError("Expected DATA_SOURCE_PUSHDOWN_DISABLED with the flag off")
        except AssertionError:
            raise
        except Exception as e:
            assert "DATA_SOURCE_PUSHDOWN_DISABLED" in str(e), f"Unexpected error with the flag off: {str(e)[:300]}"
        spark.conf.set("spark.sql.python.filterPushdown.enabled", "true")

        total = orders().count()
        assert total == 1207, f"The table has 1207 rows, the source read {total}"

        # 6. Pushed results must equal Spark's own filtering (pushdown=false), query by query
        cases = [
            ("status = 'shipped'", '"status"'),
            ("status LIKE 'ship%'", "substr("),
            ("amount > 100", '"amount"'),
            ("amount IS NULL", '"amount"'),
            ("qty IN (1, 2)", '"qty"'),
            ("order_id >= 1000 AND status = 'pending'", '"status"'),
            (sf.col("customer") == "x' OR '1'='1", '"customer"'),
        ]
        for condition, marker in cases:
            rows, queries, spark_filters = audited(orders, condition, partitionColumn="order_id",
                                                   numPartitions=3, lowerBound=1, upperBound=1201)
            ref, _, _ = audited(orders, condition, pushdown="false")
            assert rows == ref, (
                f"{condition}: the pushed query returned {len(rows)} rows but Spark's own filter gives "
                f"{len(ref)}. Your SQL must keep exactly the rows Spark would keep (think of 'N/A' "
                "amounts, 'Shipped' with a capital S, and NULLs)")
            assert len(queries) == 3, f"{condition}: expected one audited query per partition (3), got {len(queries)}"
            for q in queries:
                where = q["sql"].split(" WHERE ", 1)[-1]
                assert marker in where, (
                    f"{condition}: the pushed filter ({marker}) is missing from the task's WHERE clause: {where}")
                assert "'" not in where.replace("'integer'", "").replace("'real'", "").replace("'text'", ""), (
                    f"{condition}: a value was pasted into the SQL text instead of a ? parameter: {where}")
        n_injection = len(audited(orders, sf.col("customer") == "x' OR '1'='1")[0])
        assert n_injection == 1, f"The customer named x' OR '1'='1 should match exactly 1 row, got {n_injection}"

        # 7. The plan: pushed filters are gone from Spark's Filter; unpushable ones stay
        rows, queries, spark_filters = audited(orders, "status = 'shipped' AND note = '42'")
        assert not any("shipped" in l for l in spark_filters), (
            f"Spark should not evaluate status = 'shipped' any more, plan has {spark_filters}")
        assert any("42" in l for l in spark_filters), f"note = '42' should stay in Spark's Filter: {spark_filters}"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            orders().filter("status = 'shipped'").explain("formatted")
        assert "PushedFilters: [IsNotNull(status), EqualTo(status,shipped)]" in buf.getvalue(), (
            "explain('formatted') should list PushedFilters: [IsNotNull(status), EqualTo(status,shipped)]")

        # 8. Range partitions over min..max are skewed by the legacy ids; quantile bounds are not
        def per_partition(**options):
            df = orders(partitionColumn="order_id", numPartitions=4, **options)
            return [r["count"] for r in df.groupBy(sf.spark_partition_id().alias("p")).count().orderBy("p").collect()]
        skewed = per_partition()
        balanced = per_partition(bounds="quantile")
        assert max(skewed) >= 1200, f"min..max ranges should put almost every row in one partition, got {skewed}"
        assert len(balanced) == 4 and max(balanced) - min(balanced) <= 1, (
            f"quantile bounds should give 4 partitions within one row of each other, got {balanced}")

        # 9. Snapshot mark, without Spark: rows inserted after planning are not read
        copy = os.path.join(work, "copy.db")
        shutil.copy(db, copy)
        schema = spark.read.format("sqlite").option("path", copy).option("table", "orders").load().schema
        reader = SqliteReader({"path": copy, "table": "orders", "partitionColumn": "order_id",
                               "numPartitions": "2"}, schema)
        parts = reader.partitions()
        first = list(reader.read(parts[0]))
        w = sqlite3.connect(copy)
        w.execute("INSERT INTO orders (order_id, customer, status) VALUES (999999, 'Late', 'pending')")
        w.commit()
        w.close()
        second = list(reader.read(parts[1]))
        assert len(first) + len(second) == 1207, (
            f"Rows inserted after partitions() ran should not be read (got {len(first) + len(second)}); "
            "build_query must include rowid <= ? with the partition's snapshot mark")

        # 10. The 4.2.0 trap from "Filter Pushdown": a reused DataFrame keeps the last pushed plan
        reused = orders()
        shipped = reused.filter("status = 'shipped'").count()
        stale = reused.count()

        print("Rows per partition, min..max ranges:", skewed)
        print("Rows per partition, quantile ranges:", balanced)
        print(f"Reused DataFrame after a pushed filter: {stale} rows (status = 'shipped' had {shipped}); "
              f"fresh load(): {orders().count()} rows")
        print("SQL one task ran for amount > 100:")
        q = audited(orders, "amount > 100", partitionColumn="order_id", numPartitions=2)[1]
        q = sorted(q, key=lambda x: x["partition"])[0]
        print("  ", q["sql"])
        print("   params:", q["params"])
        orders().filter("amount IS NULL").groupBy("status").count().orderBy("status").show()
        print("All tests passed!")
    finally:
        spark.stop()
