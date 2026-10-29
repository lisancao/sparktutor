"""
Tuning Python on Spark - Exercise

An error report over the web server log, first written the slow way (row-at-a-time
Python UDFs for parsing, a Python filter, a write that scatters small files), then
tuned: built-ins for everything Spark can do itself, one vectorized pandas UDF for
the part it cannot, placed after the filter, computed once for two outputs, and
written with one file per folder. The checks look at plans, call counts and files,
never at timings.
"""

import ipaddress
import os
import re

import pandas as pd

from pyspark.sql import SparkSession, functions as sf

LOG = "data/messy/logs/access.log"
LINE = r'^(\S+) \S+ \S+ \[[^\]]+\] "\S+ (\S+) \S+" (\d{3}) (\d+)'
NETWORKS = [(ipaddress.ip_network("10.0.0.0/23"), "office"),
            (ipaddress.ip_network("10.0.2.0/24"), "vpn")]


def network_of(ip):
    """Which internal network an address belongs to (plain Python, written for you)."""
    if ip is None:
        return None
    address = ipaddress.ip_address(ip)
    for net, name in NETWORKS:
        if address in net:
            return name
    return "other"


# ---- The slow job (written for you; do not change it) ----

def slow_report(lines, counter):
    """Row-at-a-time UDFs re-parse every line four times, and a Python filter hides the condition."""
    def field(i, cast):
        def get(line):
            m = re.match(LINE, line)
            return cast(m.group(i)) if m else None
        return get

    ip = sf.udf(field(1, str), "string", useArrow=False)
    path = sf.udf(field(2, str), "string", useArrow=False)
    status = sf.udf(field(3, int), "int", useArrow=False)
    size = sf.udf(field(4, int), "bigint", useArrow=False)
    is_error = sf.udf(lambda s: s is not None and s >= 400, "boolean", useArrow=False)

    def counted_network(ip):
        counter.add(1)
        return network_of(ip)
    network = sf.udf(counted_network, "string", useArrow=False)

    parsed = lines.select(ip("value").alias("ip"), path("value").alias("path"),
                          status("value").alias("status"), size("value").alias("bytes"))
    return parsed.filter(is_error("status")).withColumn("network", network("ip"))


def slow_write(enriched, out):
    enriched.repartition(8).write.mode("overwrite").partitionBy("status").parquet(out)


# ---- Part 1: built-ins for the parse ----

def parse(lines):
    """ip, path, status int, bytes bigint from each line, with built-in functions only."""
    # TODO 1: select four columns from the line ("value") with sf.regexp_extract(value, LINE, n)
    # for groups 1 to 4: ip, path, status (cast to int), bytes (cast to bigint)
    return None


# ---- Part 2: a built-in filter, before any Python ----

def errors_only(parsed):
    """Rows with status 400 or more."""
    # TODO 2: a built-in filter on status
    return None


# ---- Part 3: one vectorized UDF for what Spark cannot do itself ----

def make_network_udf(counter):
    """A pandas UDF (Series to Series) that maps each ip with network_of, adding len(batch) to counter."""
    # TODO 3: define a @sf.pandas_udf("string") function of a pd.Series that calls
    # counter.add(len(series)) and returns series.map(network_of); return that function
    return None


# ---- Part 4: compose, and compute the Python part once ----

def fast_report(lines, counter):
    """The same rows as slow_report, cached so that two outputs run the UDF once."""
    # TODO 4: parse, keep the errors, add network = make_network_udf(counter)("ip"), and cache
    return None


# ---- Part 5: one file per status folder ----

def write_by_status(enriched, out):
    """Parquet partitioned by status, with exactly one file in each status=... folder."""
    # TODO 5: write Parquet to out (mode "overwrite") partitioned by status, so that
    # every status=... folder gets exactly one file
    enriched.write.mode("overwrite").partitionBy("status").parquet(out)


def summary(enriched):
    return enriched.groupBy("network", "status").count()


# ---- Test harness ----
if __name__ == "__main__":
    import contextlib
    import io
    import tempfile

    spark = (SparkSession.builder
        .appName("TuningPython")
        .master("local[4]")
        # Pretend the 21 KB log is a big one: split it into 8 KB pieces, so the read has 3 partitions
        .config("spark.sql.files.maxPartitionBytes", "8KB")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    def plan(df):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            df.explain()
        return buf.getvalue()

    def files_per_folder(root):
        return {d: len([f for f in os.listdir(os.path.join(root, d)) if f.endswith(".parquet")])
                for d in sorted(os.listdir(root)) if d.startswith("status=")}

    work = tempfile.mkdtemp(prefix="tuning_")
    try:
        lines = spark.read.text(LOG)
        assert lines.rdd.getNumPartitions() == 3, "The log should be read as 3 partitions"

        # The reference: the slow job's rows, summary and layout
        slow_calls = spark.sparkContext.accumulator(0)
        slow = slow_report(lines, slow_calls)
        slow_rows = sorted(slow.collect())
        slow_summary = sorted(summary(slow).collect())
        slow_write(slow, os.path.join(work, "slow"))
        slow_files = files_per_folder(os.path.join(work, "slow"))
        slow_plan = plan(slow)

        # 1. The parse uses built-ins only
        parsed = parse(lines)
        assert parsed is not None, "parse(lines) should return a DataFrame"
        assert parsed.columns == ["ip", "path", "status", "bytes"], (
            f"parse() should return the columns ip, path, status, bytes; got {parsed.columns}")
        assert dict(parsed.dtypes) == {"ip": "string", "path": "string", "status": "int", "bytes": "bigint"}, (
            f"parse() types should be string, string, int, bigint; got {parsed.dtypes}")
        p = plan(parsed)
        assert "EvalPython" not in p, (
            "parse() should not need Python: use sf.regexp_extract(value, LINE, group) and cast. "
            f"Its plan has a Python node:\n{p}")

        # 2. The filter is a built-in, so Spark can see it
        errs = errors_only(parsed)
        assert errs is not None, "errors_only() should return a DataFrame"
        ep = plan(errs)
        assert "EvalPython" not in ep and any("Filter" in l and ">= 400" in l for l in ep.splitlines()), (
            "errors_only() should filter with a built-in condition, sf.col('status') >= 400, "
            f"so that the plan has a Filter Spark understands and no Python node:\n{ep}")

        # 3 and 4. One vectorized Python node, above the filter, run once for two outputs
        calls = spark.sparkContext.accumulator(0)
        enriched = fast_report(lines, calls)
        assert enriched is not None, "fast_report() should return a DataFrame"
        fp = plan(enriched)
        assert "BatchEvalPython" not in fp, (
            "No row-at-a-time Python node should be left (BatchEvalPython). Use @sf.pandas_udf")
        assert fp.count("ArrowEvalPython") == 1, (
            f"Exactly one Python node is expected (the network UDF), found "
            f"{fp.count('ArrowEvalPython')}:\n{fp}")
        lines_of_plan = fp.splitlines()
        python_at = next(i for i, l in enumerate(lines_of_plan) if "ArrowEvalPython" in l)
        filter_at = [i for i, l in enumerate(lines_of_plan) if "Filter" in l and ">= 400" in l]
        assert filter_at and filter_at[0] > python_at, (
            "The status filter must run before the Python UDF (appear below it in the plan), so "
            "Python only sees error rows")
        assert "InMemoryRelation" in fp, "fast_report() should cache the enriched rows"

        out = os.path.join(work, "fast")
        write_by_status(enriched, out)
        fast_summary = sorted(summary(enriched).collect())
        fast_rows = sorted(enriched.collect())
        n_errors = len(fast_rows)
        assert calls.value == n_errors, (
            f"The network UDF should process each of the {n_errors} error rows exactly once across "
            f"the write, the summary and collect(); it processed {calls.value}. Filter first, and "
            "cache the enriched DataFrame so later actions reuse it")

        # 5. Same answers, better layout
        assert fast_rows == slow_rows, "fast_report() must return the same rows as slow_report()"
        assert fast_summary == slow_summary, "The summary must match the slow job's"
        fast_files = files_per_folder(out)
        assert sorted(fast_files) == sorted(slow_files), (
            f"Expected the folders {sorted(slow_files)}, got {sorted(fast_files)}")
        assert all(n == 1 for n in fast_files.values()), (
            f"Each status folder should hold exactly one file, got {fast_files}. "
            "repartition('status') before partitionBy('status') sends each status to one task")
        back = spark.read.parquet(out)
        assert back.count() == n_errors, "Reading the output back should give every error row"

        print(f"Error rows: {n_errors}")
        print(f"Network UDF calls: slow {slow_calls.value}, fast {calls.value}")
        print("Python nodes in the plan: slow", slow_plan.count("EvalPython"),
              "(BatchEvalPython)", "fast", fp.count("ArrowEvalPython"), "(ArrowEvalPython)")
        print("Files per folder: slow", slow_files, "fast", fast_files)
        summary(enriched).orderBy("network", "status").show()
        enriched.unpersist()
        print("All tests passed!")
    finally:
        spark.stop()
