"""
Text and Logs - Exercise

Turn raw log files into typed records:
- an Apache-style access log into columns, with unparseable lines set aside
- an application log with multi-line stack traces, whose format switches
  from plain text to JSON lines half way through, into one row per event
- a Latin-1 text file into a correctly decoded string
"""

from pyspark.sql import SparkSession, functions as F

# ip, identity, user, [time], "method url protocol", status, bytes
ACCESS_RE = r'^(\S+) \S+ \S+ \[([^\]]+)\] "(\S+) (\S+) (\S+)" (\d{3}) (\d+)'
ACCESS_TS = "dd/MMM/yyyy:HH:mm:ss Z"   # 01/Oct/2026:10:00:00 +0000

# A new application log event starts with a date (text format) or "{" (JSON)
EVENT_START = r"\n(?=\d{4}-\d{2}-\d{2} |\{)"
TEXT_TS = "yyyy-MM-dd HH:mm:ss,SSS"   # 2026-10-01 10:00:00,123
JSON_TS = "yyyy-MM-dd'T'HH:mm:ssX"    # 2026-10-01T11:00:00Z


def parse_access(spark, folder):
    """Parse every access log in `folder`.

    Returns (parsed, rejects):
      parsed:  ip, ts (timestamp), method, path (no query string), session,
               status (int), bytes (long), file
      rejects: value (the raw line), file, for lines that do not match
               ACCESS_RE or whose timestamp does not parse
    """
    # TODO 1: read the folder with spark.read.text and add a "file" column
    #   from _metadata.file_name
    lines = None

    def group(i):
        return F.regexp_extract("value", ACCESS_RE, i)

    # TODO 2: from `lines`, select value, file, a boolean "matched"
    #   (F.col("value").rlike(ACCESS_RE)) and the typed fields:
    #   ip = group(1); ts = F.try_to_timestamp(group(2), F.lit(ACCESS_TS));
    #   method = group(3); path = the part of group(4) before "?" (F.split_part);
    #   session = F.try_parse_url(group(4), F.lit("QUERY"), F.lit("session"));
    #   status = group(6) as int; bytes = group(7) as long
    candidates = None

    # TODO 3: a line is good when it matched AND its ts is not NULL.
    #   parsed = good lines with ip, ts, method, path, session, status, bytes, file
    #   rejects = the other lines with value, file
    parsed = None
    rejects = None
    return parsed, rejects


def app_events(spark, path):
    """One row per application log event: ts, level, ms, fmt, exception, frames.

    fmt is "text" or "json"; exception is the exception class of an ERROR
    event (NULL otherwise); frames is the list of "at ..." methods.
    """
    # TODO 4: read the whole file as ONE row (text(path, wholetext=True); an
    #   .option("wholetext", ...) before .text() is silently overridden),
    #   split "value" on EVENT_START, explode into a column "rec", and drop
    #   empty records
    recs = None

    is_json = F.col("rec").startswith("{")
    j = F.try_parse_json("rec")

    # TODO 5: select, using F.when(is_json, <json way>).otherwise(<text way>):
    #   ts:    json: try_to_timestamp of try_variant_get(j, "$.ts", "string") with JSON_TS
    #          text: try_to_timestamp of regexp_extract("rec", r"^(\S+ \S+)", 1) with TEXT_TS
    #   level: json: try_variant_get(j, "$.level", "string")
    #          text: regexp_extract("rec", r"^\S+ \S+ (\w+)", 1)
    #   ms:    json: try_variant_get(j, "$.ms", "int")
    #          text: regexp_extract("rec", r"ms=(\d+)", 1), then .try_cast("int")
    #   fmt:   "json" or "text"
    #   exception: regexp_extract("rec", r"\n([\w.$]+(?:Exception|Error)):", 1),
    #          with "" turned into NULL (F.nullif(..., F.lit("")))
    #   frames: F.regexp_extract_all("rec", F.lit(r"\tat ([\w.$]+)\("), F.lit(1))
    #          (the pattern must be wrapped in F.lit: a bare string is a column name)
    return None


def error_counts(parsed):
    """Per URL path: hits and errors (status >= 500), most errors first, then path."""
    # TODO 6: group by path; hits = count(*), errors = sum of (status >= 500)
    #   cast to int; order by errors descending, then path
    return None


def read_latin1(spark, path):
    """file_name and text of Latin-1 files, decoded correctly."""
    # TODO 7: the text source always decodes UTF-8. Read the bytes with
    #   binaryFile and decode "content" with F.decode(..., "ISO-8859-1")
    return None


# ---- Test harness ----
if __name__ == "__main__":
    import os
    import re
    import shutil
    import tempfile
    from collections import Counter

    spark = (SparkSession.builder
             .appName("TextAndLogs")
             .master("local[*]")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    # A log folder: the real access.log plus a second file with one good
    # line, one truncated line and one line with an impossible date
    logs = tempfile.mkdtemp(prefix="access_")
    shutil.copy("data/messy/logs/access.log", logs)
    with open(os.path.join(logs, "access_extra.log"), "w") as f:
        f.write('10.0.9.9 - - [01/Oct/2026:10:59:59 +0000] "GET /cart?session=s99 HTTP/1.1" 500 123 "-" "curl/8.0"\n')
        f.write('10.0.9.9 - - [01/Oct/2026:11:00:00 +0000] "GET /cart\n')
        f.write('10.0.9.9 - - [31/Sep/2026:11:00:00 +0000] "GET / HTTP/1.1" 200 10 "-" "curl/8.0"\n')

    try:
        # The wholetext gotcha, checked so a change in PySpark is noticed:
        # the text() keyword (default False) overrides an earlier .option()
        app = "data/messy/logs/app.log"
        assert spark.read.option("wholetext", True).text(app).count() == 134, "expected .option() to be overridden"
        assert spark.read.text(app, wholetext=True).count() == 1, "text(path, wholetext=True) should give one row"

        result = parse_access(spark, logs)
        assert result is not None, "parse_access() returned None: complete TODOs 1 to 3"
        parsed, rejects = result
        assert parsed is not None and rejects is not None, "parse_access() must return two DataFrames (parsed, rejects): complete TODOs 1 to 3"
        assert parsed.columns == ["ip", "ts", "method", "path", "session", "status", "bytes", "file"], (
            f"parsed columns are {parsed.columns}")
        parsed = parsed.cache()

        n_parsed, n_rejects = parsed.count(), rejects.count()
        assert n_parsed + n_rejects == 203, f"Lines went missing: {n_parsed} parsed + {n_rejects} rejected != 203"
        assert n_rejects == 2, (
            f"Expected 2 rejected lines (the truncated one and 31/Sep), got {n_rejects}. "
            "Reject lines that don't match the regex OR whose timestamp is NULL (try_to_timestamp)")
        bad = sorted(r["value"][:40] for r in rejects.collect())
        assert all("10.0.9.9" in b for b in bad), f"Wrong lines rejected: {bad}"

        dtypes = dict(parsed.dtypes)
        assert dtypes["ts"] == "timestamp" and dtypes["status"] == "int" and dtypes["bytes"] == "bigint", (
            f"Expected ts timestamp, status int, bytes bigint (long); got {dtypes}")
        first = parsed.filter((F.col("file") == "access.log")).orderBy("ts").select(
            F.date_format("ts", "yyyy-MM-dd HH:mm:ss").alias("t"), "ip", "path", "session").first()
        assert tuple(first) == ("2026-10-01 10:00:00", "10.0.2.238", "/", "s1"), (
            f"First access line parsed as {tuple(first)}; ts should be 10:00:00 UTC, path without '?...', "
            "session from the query string")
        assert parsed.filter(F.col("path").contains("?") | F.col("session").isNull()).count() == 0, (
            "Every path should have its query string removed and every line has a session")

        # Expected per-path errors, computed here in plain Python
        expected = Counter()
        hits = Counter()
        for line in open("data/messy/logs/access.log"):
            m = re.match(ACCESS_RE, line)
            p = m.group(4).split("?")[0]
            hits[p] += 1
            expected[p] += int(m.group(6)) >= 500
        hits["/cart"] += 1
        expected["/cart"] += 1   # the good extra line
        counts = error_counts(parsed)
        assert counts is not None, "error_counts() returned None: complete TODO 6"
        got = [(r["path"], r["hits"], r["errors"]) for r in counts.collect()]
        want = sorted(((p, hits[p], expected[p]) for p in hits), key=lambda t: (-t[2], t[0]))
        assert got == want, f"error_counts should be {want}, got {got}"

        events = app_events(spark, app)
        assert events is not None, "app_events() returned None: complete TODOs 4 and 5"
        assert events.columns == ["ts", "level", "ms", "fmt", "exception", "frames"], f"events columns: {events.columns}"
        events = events.cache()
        n = events.count()
        assert n == 80, (
            f"Expected 80 events (60 text + 20 JSON), got {n}. Read the file with "
            "text(path, wholetext=True) and split on EVENT_START")
        by_fmt = {r["fmt"]: r["count"] for r in events.groupBy("fmt").count().collect()}
        assert by_fmt == {"text": 60, "json": 20}, f"Events per format should be text 60, json 20; got {by_fmt}"
        for c in ["ts", "level", "ms"]:
            missing = events.filter(F.col(c).isNull() | (F.col(c).cast("string") == "")).count()
            assert missing == 0, f"{missing} events have no {c}"
        levels = {r["level"]: r["count"] for r in events.groupBy("level").count().collect()}
        assert levels == {"INFO": 46, "WARN": 16, "ERROR": 18}, f"Events per level: {levels}"
        errors = events.filter(F.col("level") == "ERROR").collect()
        for e in errors:
            assert e["exception"] == "java.lang.IllegalStateException", f"ERROR without its exception: {e}"
            assert e["frames"] == ["order.Inventory.reserve", "order.Service.process"], f"Wrong frames: {e['frames']}"
        assert events.filter((F.col("level") != "ERROR") & F.col("exception").isNotNull()).count() == 0, (
            "Only ERROR events have an exception")
        last = events.orderBy(F.desc("ts")).select(F.date_format("ts", "yyyy-MM-dd HH:mm:ss"), "fmt").first()
        assert tuple(last) == ("2026-10-01 11:19:00", "json"), f"Latest event should be the last JSON line, got {last}"

        latin = read_latin1(spark, "data/messy/docs/notes_latin1.txt")
        assert latin is not None, "read_latin1() returned None: complete TODO 7"
        text = latin.first()["text"]
        assert text == "Café crème, résumé: déjà vu.\n", (
            f"Decoded text is {text!r}. The text source always reads UTF-8; read the bytes with "
            "binaryFile and decode them with F.decode(content, 'ISO-8859-1')")

        print("Access log, first rows:")
        parsed.orderBy("ts").show(3, truncate=False)
        print("Rejected lines:")
        rejects.show(truncate=False)
        print("Errors per path:")
        counts.show()
        print("Application events per format and level:")
        (events.groupBy("fmt", "level")
            .agg(F.count("*").alias("n"), F.round(F.avg("ms")).alias("avg_ms"))
            .orderBy("fmt", "level").show())
        events.filter("level = 'ERROR'").show(2, truncate=False)
        print("Latin-1 file:", repr(text))
        print("All tests passed!")
    finally:
        shutil.rmtree(logs, ignore_errors=True)
        spark.stop()
