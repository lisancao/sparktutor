"""
Python UDTFs in Depth - Solution

Two table functions over a service's key=value logs:

- kv_extract(line, spec) decides its output columns at analysis time from a
  constant spec such as 'ts:timestamp,user,action,ms:int', and returns one
  row for every line, with an _error column instead of failing or dropping
  lines it cannot parse.
- sessionize(TABLE(events) PARTITION BY user ORDER BY ts, gap_minutes) keeps
  state across the rows of one user and emits one row per session, the last
  one from terminate().
"""

import shlex
from dataclasses import dataclass
from datetime import datetime, timedelta

from pyspark.sql import SparkSession, functions as sf
from pyspark.sql.functions import udtf
from pyspark.sql.types import (
    DoubleType, IntegerType, MapType, StringType, StructType, TimestampType,
)
from pyspark.sql.udtf import AnalyzeArgument, AnalyzeResult

LOG = "data/messy/service_logs/kv.log"
SPEC = "ts:timestamp,user,action,ms:int,region"

SPARK_TYPES = {"string": StringType(), "int": IntegerType(), "double": DoubleType(),
               "timestamp": TimestampType()}


# ---- Plain Python helpers (written for you) ----

def parse_spec(spec):
    """'ts:timestamp,user' -> [('ts', 'timestamp'), ('user', 'string')]. A missing type means string."""
    fields = []
    for part in spec.split(","):
        name, _, kind = part.strip().partition(":")
        kind = kind.strip() or "string"
        if not name or kind not in SPARK_TYPES:
            raise ValueError(f"bad field {part.strip()!r} in spec {spec!r}: use name or name:type "
                             f"with a type in {sorted(SPARK_TYPES)}")
        fields.append((name.strip(), kind))
    return fields


def parse_logfmt(line):
    """(pairs, None) for a key=value line, or (None, reason) for a line with no pairs.

    Keys are lower-cased, the last of a repeated key wins, a bare word is a flag ("true"),
    and double quotes may hold spaces and backslash-escaped quotes.
    """
    if line is None or not line.strip():
        return None, "blank"
    if line.lstrip().startswith("#"):
        return None, "comment"
    try:
        tokens = shlex.split(line)
    except ValueError as e:
        return None, f"unparseable: {e}"
    pairs = {}
    for token in tokens:
        key, eq, value = token.partition("=")
        pairs[key.lower()] = value if eq else "true"
    return pairs, None


def convert(value, kind):
    """Convert a logfmt string to the spec type. Raises ValueError if it does not fit."""
    if value is None:
        return None
    if kind == "int":
        return int(value)
    if kind == "double":
        return float(value)
    if kind == "timestamp":
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


# ---- Part 1: a UDTF whose columns come from a constant argument ----

@dataclass
class SpecResult(AnalyzeResult):
    """AnalyzeResult plus the parsed spec, handed to __init__ on the executors."""
    fields: tuple = ()


class KVExtract:
    @staticmethod
    def analyze(line: AnalyzeArgument, spec: AnalyzeArgument) -> AnalyzeResult:
        if not spec.isConstantExpression or not isinstance(spec.value, str):
            raise ValueError("kv_extract: the spec must be a constant string, "
                             "for example 'ts:timestamp,user,ms:int'")
        fields = parse_spec(spec.value)
        schema = StructType()
        for name, kind in fields:
            schema = schema.add(name, SPARK_TYPES[kind])
        schema = (schema.add("_extra", MapType(StringType(), StringType()))
                        .add("_error", StringType()))
        return SpecResult(schema=schema, fields=tuple(fields))

    def __init__(self, analyze_result=None):
        self.fields = analyze_result.fields

    def eval(self, line, spec):
        pairs, error = parse_logfmt(line)
        if pairs is None:
            # One row for every line: a line with nothing to extract still says why
            yield tuple([None] * len(self.fields)) + (None, error)
            return
        values, problems = [], []
        for name, kind in self.fields:
            try:
                values.append(convert(pairs.get(name), kind))
            except ValueError:
                values.append(None)
                problems.append(f"bad {kind} for {name}: {pairs[name]!r}")
        known = {name for name, _ in self.fields}
        extra = {k: v for k, v in pairs.items() if k not in known}
        yield tuple(values) + (extra, "; ".join(problems) or None)


def extract(lines, kv_extract):
    """lines has one column, line. Return lines plus the kv_extract(line, SPEC) columns, one row per line."""
    return lines.lateralJoin(kv_extract(sf.col("line").outer(), sf.lit(SPEC)))


# ---- Part 2: a UDTF over a partitioned, ordered table argument ----

SESSION_SCHEMA = ("user string, session int, start timestamp, end timestamp, "
                  "events int, actions array<string>")


class Sessionize:
    def __init__(self):
        # A new instance for every user (every PARTITION BY value)
        self.user = None
        self.session = 0
        self.start = self.end = None
        self.actions = []

    def _finish(self):
        if self.start is not None:
            self.session += 1
            yield self.user, self.session, self.start, self.end, len(self.actions), self.actions

    def eval(self, row, gap_minutes):
        self.user = row["user"]
        ts = row["ts"]
        if self.end is not None and ts - self.end > timedelta(minutes=gap_minutes):
            yield from self._finish()
            self.start, self.actions = None, []
        if self.start is None:
            self.start = ts
        self.end = ts
        self.actions = self.actions + [row["action"]]

    def terminate(self):
        yield from self._finish()


def sessionize(events, gap_minutes, sessionize_udtf):
    """events has user, ts, action. One row per session, rows of each user in time order."""
    return sessionize_udtf(events.asTable().partitionBy("user").orderBy("ts"), sf.lit(gap_minutes))


def make_udtfs():
    """Create the UDTFs once the session exists, so they pick up the session's Arrow setting
    (and, on Spark Connect, become Connect UDTFs)."""
    return udtf(KVExtract), udtf(Sessionize, returnType=SESSION_SCHEMA)


# ---- Test harness ----
if __name__ == "__main__":
    import contextlib
    import io
    import re

    # 1. The helpers and analyze(), without Spark
    assert parse_spec("ts:timestamp,user") == [("ts", "timestamp"), ("user", "string")]
    result = KVExtract.analyze(AnalyzeArgument(StringType(), None, False, False),
                                    AnalyzeArgument(StringType(), "user,ms:int", False, True))
    assert result is not None and isinstance(result, AnalyzeResult), (
        "KVExtract.analyze should return an AnalyzeResult (your SpecResult)")
    names = [f.name for f in result.schema.fields]
    assert names == ["user", "ms", "_extra", "_error"], (
        f"For the spec 'user,ms:int' analyze() should return the columns user, ms, _extra, _error; "
        f"got {names}")
    assert result.schema["ms"].dataType == IntegerType(), "ms:int should become an IntegerType column"
    assert isinstance(result.schema["_extra"].dataType, MapType), "_extra should be map<string,string>"
    assert getattr(result, "fields", None) == (("user", "string"), ("ms", "int")), (
        "Return SpecResult(schema=..., fields=tuple(parse_spec(...))) so __init__ receives the fields")
    try:
        KVExtract.analyze(AnalyzeArgument(StringType(), None, False, False),
                               AnalyzeArgument(StringType(), None, False, False))
        raise AssertionError("analyze() should raise when the spec is not a constant expression")
    except ValueError:
        pass

    spark = (SparkSession.builder
        .appName("PythonUDTFs")
        .master("local[*]")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "4")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    def plan(df):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            df.explain()
        return buf.getvalue()

    try:
        kv_extract, sessionize_udtf = make_udtfs()
        lines = spark.read.text(LOG).withColumnRenamed("value", "line")
        n_lines = lines.count()

        # 2. kv_extract: schema from the spec, one row per line, problems in _error
        parsed = extract(lines, kv_extract)
        want = ("struct<line:string,ts:timestamp,user:string,action:string,ms:int,region:string,"
                "_extra:map<string,string>,_error:string>")
        assert parsed.schema.simpleString() == want, (
            f"extract(lines) should have the schema\n  {want}\ngot\n  {parsed.schema.simpleString()}")
        rows = parsed.collect()
        assert len(rows) == n_lines, (
            f"Every line must produce one row: {n_lines} lines, {len(rows)} rows. A line with nothing "
            "to extract should still yield a row (all NULL plus _error), so no line disappears")
        assert "ArrowEvalPythonUDTF" in plan(parsed), (
            "kv_extract should run as an Arrow-optimized UDTF (ArrowEvalPythonUDTF): create it with "
            "udtf(...) after the SparkSession exists, as make_udtfs() does")
        assert "SortMergeJoin" not in plan(parsed) and "BroadcastHashJoin" not in plan(parsed), (
            "extract() should be a plain lateral join (one ArrowEvalPythonUDTF node), not a join with "
            "ON TRUE: make the UDTF yield a row for every line instead")
        errors = [r._error for r in rows if r._error]
        assert sorted(e for e in errors if e in ("blank", "comment")) == ["blank", "blank", "comment"], (
            f"Expected two blank lines and one comment in _error, got {errors}")
        assert any(e.startswith("unparseable: No closing quotation") for e in errors), (
            f"The line cut inside a quoted value should give _error 'unparseable: No closing quotation', "
            f"got {errors}")
        bad_ms = [r for r in rows if r._error == "bad int for ms: 'fast'"]
        assert len(bad_ms) == 1 and bad_ms[0].ms is None and bad_ms[0].user == "u4", (
            "The line with ms=fast should have ms NULL, user u4 and _error \"bad int for ms: 'fast'\"")
        quoted = [r for r in rows if r._extra and r._extra.get("msg") == 'card "declined" twice']
        assert len(quoted) == 1, "msg=\"card \\\"declined\\\" twice\" should land in _extra unquoted"
        upper = [r for r in rows if r.line and "User=u6" in r.line]
        assert upper and upper[0].user == "u6", "Keys are case-insensitive: User=u6 should fill user"

        # 3. A spec that is not a constant fails at analysis, with your message
        try:
            lines.lateralJoin(kv_extract(sf.col("line").outer(), sf.col("line").outer())).collect()
            raise AssertionError("A non-constant spec should fail at analysis")
        except AssertionError:
            raise
        except Exception as e:
            assert "TABLE_VALUED_FUNCTION_FAILED_TO_ANALYZE_IN_PYTHON" in str(e) and "constant" in str(e), (
                f"Expected TABLE_VALUED_FUNCTION_FAILED_TO_ANALYZE_IN_PYTHON with your message, got {str(e)[:300]}")

        # 4. sessionize: compare with plain Python over the same lines
        events = parsed.where("user IS NOT NULL AND ts IS NOT NULL").select("user", "ts", "action")
        expected = {}
        by_user = {}
        for line in open(LOG, encoding="utf-8").read().splitlines():
            pairs, _ = parse_logfmt(line)
            if pairs and pairs.get("user") and pairs.get("ts"):
                by_user.setdefault(pairs["user"], []).append(
                    (convert(pairs["ts"], "timestamp"), pairs.get("action")))
        for user, evs in by_user.items():
            evs.sort(key=lambda e: e[0])
            sessions = [[evs[0]]]
            for e in evs[1:]:
                if e[0] - sessions[-1][-1][0] > timedelta(minutes=30):
                    sessions.append([])
                sessions[-1].append(e)
            for i, s in enumerate(sessions, start=1):
                expected[(user, i)] = (s[0][0].strftime("%Y-%m-%d %H:%M:%S"),
                                       s[-1][0].strftime("%Y-%m-%d %H:%M:%S"), len(s), [a for _, a in s])

        result = sessionize(events, 30, sessionize_udtf)
        assert result is not None, "sessionize() should return the DataFrame from sessionize_udtf(...)"
        got_rows = (result.select("user", "session", sf.col("start").cast("string").alias("start"),
                                  sf.col("end").cast("string").alias("end"), "events", "actions")
                    .collect())
        got = {(r.user, r.session): (r.start, r.end, r.events, list(r.actions)) for r in got_rows}
        assert len(got) == len(got_rows), "Each (user, session) pair should appear once"
        missing = sorted(set(expected) - set(got))
        extra = sorted(set(got) - set(expected))
        assert not missing and not extra, (
            f"Sessions differ from the reference. Missing: {missing[:5]}, unexpected: {extra[:5]}. "
            "Number sessions from 1 per user (state in __init__), and yield the last session from terminate()")
        for key in sorted(expected):
            assert got[key] == expected[key], f"Session {key}: expected {expected[key]}, got {got[key]}"
        p = plan(result)
        assert "hashpartitioning(partition_by_0" in p, (
            "sessionize() should partition the table argument by user: asTable().partitionBy('user')")
        assert re.search(r"Sort \[partition_by_0#\d+ ASC NULLS FIRST, ts#", p), (
            "sessionize() should sort each user's rows by ts: .orderBy('ts') after partitionBy")

        # 5. The same UDTF from SQL, with a TABLE argument
        spark.udtf.register("sessionize", sessionize_udtf)
        events.createOrReplaceTempView("events")
        sql_count = spark.sql(
            "SELECT * FROM sessionize(TABLE(events) PARTITION BY user ORDER BY ts, gap_minutes => 30)"
        ).count()
        assert sql_count == len(expected), f"SQL sessionize returned {sql_count} sessions, expected {len(expected)}"

        print(f"{n_lines} lines, {len(rows)} rows from kv_extract, problems: {sorted(set(errors))}")
        print(f"{len(expected)} sessions for {len(by_user)} users")
        (result.select("user", "session", "start", "end", "events")
            .orderBy("user", "session").show(8, truncate=False))
        print("All tests passed!")
    finally:
        spark.stop()
