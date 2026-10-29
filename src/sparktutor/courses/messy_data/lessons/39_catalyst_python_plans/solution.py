"""
How Catalyst Plans Python - Solution

Plan inspectors that read Spark's physical plan, both as the JVM object tree
(df._jdf.queryExecution().executedPlan(), classic sessions only) and as the
explain() text, and two query rewrites that change what Catalyst does with
Python code.
"""

import contextlib
import io
import os
import re
import shutil
import tempfile

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.datasource import DataSource, DataSourceReader, EqualTo, InputPartition

# Physical nodes that run Python code (names as SparkPlan.nodeName prints them).
PYTHON_NODES = {
    "ArrowEvalPython", "BatchEvalPython", "MapInPandas", "MapInArrow",
    "FlatMapGroupsInPandas", "FlatMapGroupsInArrow", "FlatMapCoGroupsInPandas",
    "FlatMapCoGroupsInArrow", "AggregateInPandas", "ArrowAggregatePython",
    "WindowInPandas", "ArrowWindowPython", "ArrowEvalPythonUDTF", "BatchEvalPythonUDTF",
}

LOG = r'^(\S+) \S+ \S+ \[([^\]]+)\] "(\S+) (\S+) [^"]*" (\d{3}) (\d+)'


# ---------------------------------------------------------------------------
# Part 1: walk the physical plan as JVM objects
# ---------------------------------------------------------------------------

def walk(plan, depth=0):
    """Yield (depth, node) for a JVM SparkPlan and all its descendants,
    top-down. AdaptiveSparkPlan hides its plan: descend into executedPlan()."""
    yield depth, plan
    if plan.nodeName() == "AdaptiveSparkPlan":
        yield from walk(plan.executedPlan(), depth + 1)
        return
    children = plan.children()
    for i in range(children.length()):
        yield from walk(children.apply(i), depth + 1)


def python_nodes(df):
    """Names of the physical nodes that evaluate Python, top-down."""
    plan = df._jdf.queryExecution().executedPlan()
    return [node.nodeName() for _, node in walk(plan) if node.nodeName() in PYTHON_NODES]


def filter_above_python(df, column):
    """True if some Filter whose condition uses `column` is an ancestor of a
    node that evaluates Python (so the filter runs after the Python code)."""
    plan = df._jdf.queryExecution().executedPlan()
    pattern = re.compile(rf"\b{re.escape(column)}#\d+")
    stack = []  # filters on `column` on the current root-to-node path
    for depth, node in walk(plan):
        while stack and stack[-1] >= depth:
            stack.pop()
        name = node.nodeName()
        if name in PYTHON_NODES and stack:
            return True
        if name == "Filter" and pattern.search(node.condition().toString()):
            stack.append(depth)
    return False


# ---------------------------------------------------------------------------
# Part 2: read the formatted plan text (works on Spark Connect too)
# ---------------------------------------------------------------------------

def plan_text(df, mode="formatted"):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        df.explain(mode)
    return buf.getvalue()


def pushed_filters(df):
    """Every filter pushed into a scan, as strings like 'EqualTo(status,200)'."""
    found = []
    for line in plan_text(df).splitlines():
        m = re.match(r"\s*PushedFilters: \[(.*)\]\s*$", line)
        if m and m.group(1):
            found.extend(re.split(r", (?=[A-Za-z]+\()", m.group(1)))
    return found


# ---------------------------------------------------------------------------
# Part 3: rewrites
# ---------------------------------------------------------------------------

def api_hits_one_eval(df, area):
    """Same rows as api_hits_slow: one Python evaluation per row that passes
    status = 200, and status = 200 still pushed into the Parquet scan.

    Marking the UDF nondeterministic stops PushDownPredicates from copying it
    into the Filter (so ExtractPythonUDFs makes one node), but also stops any
    filter written after it from moving below it. So filter on status first.
    """
    once = area.asNondeterministic()
    return (df.filter(F.col("status") == 200)
              .withColumn("area", once("path"))
              .filter(F.col("area") == "api"))


def errors_pushed(df):
    """Same rows as errors_slow, with the condition as a native expression so
    Parquet receives it and no Python runs."""
    return df.filter(F.col("status") >= 400)


# ---------------------------------------------------------------------------
# The queries and sources the harness uses (given)
# ---------------------------------------------------------------------------

def api_hits_slow(df, area):
    return (df.withColumn("area", area("path"))
              .filter(F.col("area") == "api")
              .filter(F.col("status") == 200))


def errors_slow(df):
    is_error = F.udf(lambda s: s >= 400, "boolean")
    return df.filter(is_error("status"))


class FilesReader(DataSourceReader):
    def __init__(self, options):
        self.root = options["path"]
        self.kinds = None

    def pushFilters(self, filters):
        for f in filters:
            if isinstance(f, EqualTo) and f.attribute == ("kind",):
                self.kinds = {f.value}
            else:
                yield f

    def partitions(self):
        files = sorted(os.path.join(d, n) for d, _, ns in os.walk(self.root) for n in ns)
        if self.kinds:
            files = [p for p in files if os.path.splitext(p)[1][1:] in self.kinds]
        return [InputPartition(files[i::2]) for i in range(2)]

    def read(self, partition):
        for p in partition.value:
            yield (p, os.path.splitext(p)[1][1:], os.path.getsize(p))


class Files(DataSource):
    @classmethod
    def name(cls):
        return "files"

    def schema(self):
        return "path string, kind string, size long"

    def reader(self, schema):
        return FilesReader(self.options)


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

def sorted_rows(df):
    return sorted(tuple(r) for r in df.collect())


if __name__ == "__main__":
    spark = (SparkSession.builder.master("local[2]")
             # 4.2.0 hangs when an Arrow-optimized UDF reads straight from a
             # Parquet scan (SPARK-58241, fixed in 4.2.1). See the lesson.
             .config("spark.sql.execution.arrow.pythonUDF.columnarInput.enabled", "false")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    tmp = tempfile.mkdtemp()

    raw = spark.read.text("data/messy/logs/access.log")
    logs = raw.select(F.regexp_extract("value", LOG, 1).alias("ip"),
                      F.regexp_extract("value", LOG, 4).alias("path"),
                      F.regexp_extract("value", LOG, 5).cast("int").alias("status"))
    logs.write.parquet(os.path.join(tmp, "access"))
    df = spark.read.parquet(os.path.join(tmp, "access"))

    calls = spark.sparkContext.accumulator(0)

    def _area(path):
        calls.add(1)
        return path.split("?")[0].split("/")[1] or "home"

    area = F.udf(_area, "string")

    def count_calls(q):
        before = calls.value
        rows = sorted_rows(q)
        return rows, calls.value - before

    # ---- Part 1: python_nodes and filter_above_python ----
    slow = api_hits_slow(df, area)
    nodes = python_nodes(slow)
    assert nodes is not None, "python_nodes returned None. Return a list of node names."
    print("Python nodes in api_hits_slow:", nodes)
    assert nodes == ["ArrowEvalPython", "ArrowEvalPython"], (
        f"python_nodes(api_hits_slow) returned {nodes}. The UDF is copied into the "
        "filter, so the plan has two ArrowEvalPython nodes. Walk every node of "
        "df._jdf.queryExecution().executedPlan() with children().")
    grouped = df.groupBy("status").applyInPandas(lambda p: p.head(1), df.schema)
    assert python_nodes(grouped) == ["FlatMapGroupsInPandas"], (
        f"python_nodes on an applyInPandas query returned {python_nodes(grouped)}. "
        "The plan starts with AdaptiveSparkPlan: descend into its executedPlan().")
    assert python_nodes(df.filter("status = 200")) == [], "A query without Python has no Python nodes."

    after_nd = df.withColumn("a", area.asNondeterministic()("path")).filter("status = 200")
    above = filter_above_python(after_nd, "status")
    assert above is True, (
        f"filter_above_python(..., 'status') returned {above} for a filter written "
        "after a nondeterministic UDF; the Filter on status sits above ArrowEvalPython.")
    assert filter_above_python(slow, "status") is False, (
        "In api_hits_slow the status filter was pushed below the Python nodes, "
        "so filter_above_python(slow, 'status') must be False.")
    assert filter_above_python(slow, "path") is False, "No filter uses path in api_hits_slow."
    print("python_nodes and filter_above_python pass")

    # ---- Part 2: pushed_filters ----
    pf = pushed_filters(slow)
    assert pf is not None, "pushed_filters returned None. Return a list of strings."
    print("Pushed into Parquet for api_hits_slow:", pf)
    assert pf == ["IsNotNull(status)", "EqualTo(status,200)"], (
        f"pushed_filters(api_hits_slow) returned {pf}. Read the 'PushedFilters: [...]' "
        "line of explain('formatted') and split it into filters.")
    assert pushed_filters(after_nd) == [], "Nothing is pushed when the filter sits above the UDF."

    spark.dataSource.register(Files)
    spark.conf.set("spark.sql.python.filterPushdown.enabled", "true")
    root = os.path.abspath("data/messy")
    big = F.udf(lambda n: n > 1000, "boolean")
    pyds = spark.read.format("files").load(root).filter((F.col("kind") == "png") & big("size"))
    assert pushed_filters(pyds) == ["EqualTo(kind,png)"], (
        f"pushed_filters on the Python data source returned {pushed_filters(pyds)}. "
        "BatchScan prints PushedFilters only in explain('formatted').")
    assert filter_above_python(pyds, "kind") is False
    print("pushed_filters passes on Parquet and on a Python data source")

    # ---- Part 3: api_hits_one_eval ----
    slow_rows, slow_calls = count_calls(slow)
    fast = api_hits_one_eval(df, area)
    assert fast is not None, "api_hits_one_eval returned None."
    fast_rows, fast_calls = count_calls(fast)
    status_200 = df.filter("status = 200").count()
    print(f"UDF calls: api_hits_slow {slow_calls}, api_hits_one_eval {fast_calls} "
          f"({status_200} rows have status 200, {len(slow_rows)} are API hits)")
    assert sorted(fast_rows) == sorted(slow_rows), "api_hits_one_eval returns different rows."
    assert python_nodes(fast) == ["ArrowEvalPython"], (
        f"api_hits_one_eval has Python nodes {python_nodes(fast)}; expected exactly one.")
    assert fast_calls == status_200, (
        f"The UDF ran {fast_calls} times; it should run once per row with status "
        f"200 ({status_200}).")
    assert "EqualTo(status,200)" in pushed_filters(fast), (
        "status = 200 is no longer pushed into Parquet. Filter on status before "
        "adding the UDF column.")

    # ---- Part 3: errors_pushed ----
    fixed = errors_pushed(df)
    assert fixed is not None, "errors_pushed returned None."
    assert sorted_rows(fixed) == sorted_rows(errors_slow(df)), "errors_pushed returns different rows."
    assert python_nodes(fixed) == [], f"errors_pushed still runs Python: {python_nodes(fixed)}"
    assert "GreaterThanOrEqual(status,400)" in pushed_filters(fixed), (
        f"Parquet did not receive status >= 400; pushed: {pushed_filters(fixed)}")
    print("Rewrites pass: one Python evaluation, filters pushed")

    spark.stop()
    shutil.rmtree(tmp)
    print("All tests passed!")
