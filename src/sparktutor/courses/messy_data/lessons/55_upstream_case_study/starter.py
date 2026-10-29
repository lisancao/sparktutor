# spark-run: python
"""
From Wrong Results to a Fix: An Upstream Case Study - Exercise

The bug: with spark.sql.python.filterPushdown.enabled=true, Spark 4.2.0
stores the read that filter pushdown planned (the read function bound to
a reader that saw the pushed filters, plus its partitions) on the
provider object, PythonDataSourceV2, which every scan of the relation
shares. Other scans then read with the wrong reader.

This exercise walks the method of the lesson:

1. LeakKVReader / minimal_repro: a source with no files and ten rows,
   and the smallest program that shows a count change.
2. planning_calls: evidence that the third query never planned a read.
3. provider_reader_state: open the provider through Py4J (classic mode)
   and unpickle the cached read function to see the reader inside it.
4. LeakRegressionTests: unittest tests that fail on 4.2.0 for the right
   reason (an assertion, not an error).
5. SafeSource: a workaround users can apply today.
6. PATCHED_SCALA: the narrow fix, compiled with the Scala compiler that
   ships in pyspark/jars and tested in a fresh JVM that loads the patched
   classes before Spark's own.

This file is run as plain `python exercise.py` (see the first line), so it
builds its own sessions. Step 6 starts a second Python process.
"""

import glob
import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest

from pyspark import cloudpickle
from pyspark.sql import SparkSession, functions as F
from pyspark.sql.datasource import DataSource, DataSourceReader, EqualTo, InputPartition

FLAG = "spark.sql.python.filterPushdown.enabled"
NAME = "leak_kv"


# ---- 1. The minimal source ----
class LeakKV(DataSource):
    """format("leak_kv"): ten rows (k, v); k is 'a' for v < 3 and 'b' otherwise."""

    @classmethod
    def name(cls):
        return NAME

    def schema(self):
        return "k string, v int"

    def reader(self, schema):
        return LeakKVReader(self.options)


class LeakKVReader(DataSourceReader):
    def __init__(self, options):
        self.k = None                       # set by pushFilters
        self.audit = options.get("audit")   # optional folder for planning markers

    def pushFilters(self, filters):
        # TODO: take over EqualTo on ("k",) (save its value in self.k and do
        # not yield it); yield every other filter back to Spark.
        yield from filters

    def partitions(self):
        # TODO (step 2): when self.audit is set, write one new file named
        # plan-<something unique> into that folder on every call.
        return [InputPartition(0)]

    def read(self, partition):
        # TODO: yield (k, v) for v in 0..9, with k = "a" for v < 3 and "b"
        # otherwise; keep only k == self.k when a filter was pushed.
        return iter([])


def minimal_repro(spark):
    """(count, filtered count, count again) on one reused DataFrame."""
    # TODO: load leak_kv ONCE, then return the three counts.
    return None


# ---- 2. Evidence: how many reads were planned per query ----
def planning_calls(spark, audit_dir):
    """Planned reads for: df.count(), df.filter(k = 'a').count(), df.count()."""
    # TODO: load leak_kv once with .option("audit", audit_dir), run the three
    # queries, and return how many plan-* markers each one added.
    return None


# ---- 3. Evidence: the reader inside the provider's cached read ----
def private(obj, field):
    """Read a private field of a JVM object through Java reflection (given)."""
    f = obj.getClass().getDeclaredField(field)
    f.setAccessible(True)
    return f.get(obj)


def provider_reader_state(df):
    """vars() of the reader inside the read cached on df's provider, or None.

    Classic mode only: walks df._jdf to the DataSourceV2Relation, its
    PythonTable, the table's PythonDataSourceV2 (field `ds`) and that
    provider's `readInfo`. readInfo.func() is a pickled
    (data_source_read_func, schema) pair; the reader is a free variable
    of that function.
    """
    # TODO: df._jdf.queryExecution().analyzed() -> DataSourceV2Relation
    # (walk .child() if needed) -> .table() -> private(table, "ds") ->
    # private(provider, "readInfo") (None until a read was planned) ->
    # cloudpickle.loads(bytes(info.func())) -> the reader among the function's
    # free variables (inspect.getclosurevars) -> dict(vars(reader)).
    return None


# ---- 4. Regression tests ----
class LeakTestBase(unittest.TestCase):
    """Given. The harness sets `spark` and `factory`.

    `self.make()` returns the DataFrame to use for one reference to the
    source. The harness runs your tests twice: once with a factory that
    hands out the same DataFrame every time (what users do, and what
    exposes the bug) and once with a factory that loads afresh.
    """
    spark = None
    factory = None

    def setUp(self):
        self.make = type(self).factory()


class LeakRegressionTests(LeakTestBase):
    # Call self.make() once per reference to the source, and assert with
    # self.assertEqual so a wrong count is a failure, not an error.

    def test_reused_dataframe(self):
        # TODO: a filtered count (3), then an unfiltered count (10)
        pass

    def test_self_union_in_one_query(self):
        # TODO: union of the whole source and its k = 'a' rows (13 rows)
        pass

    def test_self_join_keeps_the_filter(self):
        # TODO: join two references on v, keep x.k = 'a' (3 rows)
        pass


# ---- 5. A workaround users can apply on 4.2.0 ----
class SafeSource:
    """Read a Python data source with pushdown on, without the 4.2.0 leak.

    table() loads afresh on every call, so no two scans share a provider:
    call it once per reference to the source, even inside one query.
    snapshot() reads everything once, from its own fresh load, and keeps
    the rows in Spark; later queries never reach the source again.
    """

    def __init__(self, spark, fmt, **options):
        self.spark, self.fmt, self.options = spark, fmt, options

    def table(self):
        # TODO: a new spark.read.format(...).option(...).load() on every call
        return None

    def snapshot(self):
        # TODO: read everything once from a fresh load and keep it in Spark
        return None


# ---- 6. The narrow fix, as patched Scala sources ----
ASF_HEADER = """/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *    http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
"""

PATCHED_SCALA = {
    "PythonDataSourceV2.scala": ASF_HEADER + r'''package org.apache.spark.sql.execution.datasources.v2.python

import org.apache.spark.sql.SparkSession
import org.apache.spark.sql.connector.catalog._
import org.apache.spark.sql.connector.expressions.Transform
import org.apache.spark.sql.types.StructType
import org.apache.spark.sql.util.CaseInsensitiveStringMap

/**
 * Data Source V2 wrapper for Python Data Source.
 */
class PythonDataSourceV2 extends TableProvider {
  private var name: String = _

  def setShortName(str: String): Unit = {
    assert(name == null)
    name = str
  }

  private def shortName: String = {
    assert(name != null)
    name
  }

  private var dataSourceInPython: PythonDataSourceCreationResult = _
  private[python] lazy val source: UserDefinedPythonDataSource =
    SparkSession.active.sessionState.dataSourceManager.lookupDataSource(shortName)

  def getOrCreateDataSourceInPython(
      shortName: String,
      options: CaseInsensitiveStringMap,
      userSpecifiedSchema: Option[StructType]): PythonDataSourceCreationResult = {
    if (dataSourceInPython == null) {
      dataSourceInPython = source.createDataSourceInPython(shortName, options, userSpecifiedSchema)
    }
    dataSourceInPython
  }

  private var readInfo: PythonDataSourceReadInfo = _

  def getOrCreateReadInfo(
      shortName: String,
      options: CaseInsensitiveStringMap,
      outputSchema: StructType,
      isStreaming: Boolean
  ): PythonDataSourceReadInfo = {
    if (readInfo == null) {
      val creationResult = getOrCreateDataSourceInPython(shortName, options, Some(outputSchema))
      readInfo = source.createReadInfoInPython(creationResult, outputSchema, isStreaming)
    }
    readInfo
  }

  // TODO: this setter is how pushdown state reaches every scan of the provider.
  def setReadInfo(readInfo: PythonDataSourceReadInfo): Unit = {
    this.readInfo = readInfo
  }

  override def inferSchema(options: CaseInsensitiveStringMap): StructType = {
    getOrCreateDataSourceInPython(shortName, options, None).schema
  }

  override def getTable(
      schema: StructType,
      partitioning: Array[Transform],
      properties: java.util.Map[String, String]): Table = {
    new PythonTable(this, shortName, schema)
  }

  override def supportsExternalMetadata(): Boolean = true
}
''',
    "PythonScanBuilder.scala": ASF_HEADER + r'''package org.apache.spark.sql.execution.datasources.v2.python

import org.apache.spark.sql.connector.read.{Scan, ScanBuilder, SupportsPushDownFilters}
import org.apache.spark.sql.internal.SQLConf
import org.apache.spark.sql.sources.Filter
import org.apache.spark.sql.types.StructType
import org.apache.spark.sql.util.CaseInsensitiveStringMap


class PythonScanBuilder(
    ds: PythonDataSourceV2,
    shortName: String,
    outputSchema: StructType,
    options: CaseInsensitiveStringMap)
    extends ScanBuilder
    with SupportsPushDownFilters {
  private var supportedFilters: Array[Filter] = Array.empty

  override def build(): Scan =
    new PythonScan(ds, shortName, outputSchema, options, supportedFilters)

  // Optionally called by DSv2 once to push down filters before the scan is built.
  override def pushFilters(filters: Array[Filter]): Array[Filter] = {
    if (!SQLConf.get.pythonFilterPushDown) {
      return filters
    }

    val dataSource = ds.getOrCreateDataSourceInPython(shortName, options, Some(outputSchema))
    ds.source.pushdownFiltersInPython(dataSource, outputSchema, filters) match {
      case None => filters // No filters are supported.
      case Some(result) =>
        // Filter pushdown also returns partitions and the read function.
        // This helps reduce the number of Python worker calls.
        // TODO: keep this read info on the scan builder instead, and hand it to PythonScan.
        ds.setReadInfo(result.readInfo)

        // Partition the filters into supported and unsupported ones.
        val isPushed = result.isFilterPushed.zip(filters)
        supportedFilters = isPushed.collect { case (true, filter) => filter }.toArray
        val unsupported = isPushed.collect { case (false, filter) => filter }.toArray
        unsupported
    }
  }

  override def pushedFilters(): Array[Filter] = supportedFilters
}
''',
    "PythonScan.scala": ASF_HEADER + r'''package org.apache.spark.sql.execution.datasources.v2.python

import org.apache.spark.JobArtifactSet
import org.apache.spark.sql.classic.SparkSession
import org.apache.spark.sql.connector.metric.CustomMetric
import org.apache.spark.sql.connector.read._
import org.apache.spark.sql.connector.read.streaming.MicroBatchStream
import org.apache.spark.sql.internal.connector.SupportsMetadata
import org.apache.spark.sql.sources.Filter
import org.apache.spark.sql.types.StructType
import org.apache.spark.sql.util.CaseInsensitiveStringMap

class PythonScan(
    ds: PythonDataSourceV2,
    shortName: String,
    outputSchema: StructType,
    options: CaseInsensitiveStringMap,
    supportedFilters: Array[Filter]
) extends Scan with SupportsMetadata {
  override def toBatch: Batch = new PythonBatch(ds, shortName, outputSchema, options)

  override def toMicroBatchStream(checkpointLocation: String): MicroBatchStream = {
    val runner = PythonMicroBatchStream.createPythonStreamingSourceRunner(
      ds, shortName, outputSchema, options)
    runner.init()

    val supportedFeatures = runner.checkSupportedFeatures()

    if (supportedFeatures.triggerAvailableNow) {
      new PythonMicroBatchStreamWithTriggerAvailableNow(
        ds, shortName, outputSchema, options, runner)
    } else if (supportedFeatures.admissionControl) {
      new PythonMicroBatchStreamWithAdmissionControl(
        ds, shortName, outputSchema, options, runner)
    } else {
      new PythonMicroBatchStream(ds, shortName, outputSchema, options, runner)
    }
  }

  override def description: String = "(Python)"

  override def readSchema(): StructType = outputSchema

  override def supportedCustomMetrics(): Array[CustomMetric] =
    ds.source.createPythonMetrics()

  override def columnarSupportMode(): Scan.ColumnarSupportMode =
    Scan.ColumnarSupportMode.UNSUPPORTED

  override def getMetaData(): Map[String, String] = {
    Map(
      "PushedFilters" -> supportedFilters.mkString("[", ", ", "]"),
      "ReadSchema" -> outputSchema.simpleString
    )
  }
}

class PythonBatch(
    ds: PythonDataSourceV2,
    shortName: String,
    outputSchema: StructType,
    options: CaseInsensitiveStringMap) extends Batch {
  private val jobArtifactUUID = JobArtifactSet.getCurrentJobArtifactState.map(_.uuid)
  private val sessionUUID = {
    SparkSession.getActiveSession.collect {
      case session if session.sessionState.conf.pythonWorkerLoggingEnabled =>
        session.sessionUUID
    }
  }

  // TODO: use the read info planned during pushdown when this scan has one;
  // fall back to the provider's cache only when nothing was pushed.
  private lazy val infoInPython: PythonDataSourceReadInfo = {
    ds.getOrCreateReadInfo(shortName, options, outputSchema, isStreaming = false)
  }

  override def planInputPartitions(): Array[InputPartition] =
    infoInPython.partitions.zipWithIndex.map(p => PythonInputPartition(p._2, p._1)).toArray

  override def createReaderFactory(): PartitionReaderFactory = {
    val readerFunc = infoInPython.func
    new PythonPartitionReaderFactory(
      ds.source, readerFunc, outputSchema, jobArtifactUUID, sessionUUID)
  }
}
''',
}


# ---- Test harness ----
PACKAGE_DIR = "org/apache/spark/sql/execution/datasources/v2/python"


def new_session(extra_classpath=None):
    builder = (SparkSession.builder.master("local[2]")
               .appName("UpstreamCaseStudy")
               .config(FLAG, "true")
               .config("spark.ui.enabled", "false"))
    if extra_classpath:
        builder = builder.config("spark.driver.extraClassPath", extra_classpath)
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    spark.dataSource.register(LeakKV)
    return spark


def run_tests(spark, factory, only=None):
    """Run LeakRegressionTests with `factory`; {test name: 'ok' | 'fail' | 'error: ...'}."""
    LeakTestBase.spark, LeakTestBase.factory = spark, staticmethod(factory)
    names = only or sorted(n for n in dir(LeakRegressionTests) if n.startswith("test_"))
    outcome = {}
    for name in names:
        result = unittest.TestResult()
        LeakRegressionTests(name).run(result)
        if result.failures:
            outcome[name] = "fail"
        elif result.errors:
            outcome[name] = "error: " + result.errors[0][1].strip().splitlines()[-1][:300]
        else:
            outcome[name] = "ok"
    return outcome


def shared_factory(spark):
    """Every make() returns the same DataFrame: the way users reuse one."""
    def factory():
        df = spark.read.format(NAME).load()
        return lambda: df
    return factory


def fresh_factory(spark):
    return lambda: SafeSource(spark, NAME).table


def compile_patch(out):
    """Compile PATCHED_SCALA with the Scala compiler shipped in pyspark/jars."""
    import pyspark

    src = os.path.join(out, "src", PACKAGE_DIR)
    os.makedirs(src)
    for name, code in PATCHED_SCALA.items():
        with open(os.path.join(src, name), "w") as f:
            f.write(code)
    classes = os.path.join(out, "classes")
    os.makedirs(classes)
    jars = os.path.join(os.path.dirname(pyspark.__file__), "jars", "*")
    r = subprocess.run(["java", "-cp", jars, "scala.tools.nsc.Main", "-usejavacp", "-nowarn",
                        "-d", classes, *sorted(glob.glob(os.path.join(src, "*.scala")))],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError("Your patched Scala does not compile:\n" + (r.stdout + r.stderr)[-3000:])
    return classes


def patched_run(classes):
    """In a fresh JVM with the patched classes first: run the tests with shared DataFrames."""
    spark = new_session(extra_classpath=classes)
    try:
        jvm = spark._jvm
        cls = jvm.java.lang.Class.forName(
            "org.apache.spark.sql.execution.datasources.v2.python.PythonScanBuilder")
        loaded_from = cls.getProtectionDomain().getCodeSource().getLocation().getPath()
        outcome = run_tests(spark, shared_factory(spark))
        df = spark.read.format(NAME).load()
        counts = [df.count(), df.filter("k = 'a'").count(), df.count()]
        state = provider_reader_state(df)
        print(json.dumps({"loaded_from": loaded_from, "tests": outcome,
                          "counts": counts, "provider_state": state}))
    finally:
        spark.stop()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--patched":
        patched_run(sys.argv[2])
        sys.exit(0)

    spark = new_session()
    try:
        # 1. The minimal repro shows the bug on stock 4.2.0
        got = minimal_repro(spark)
        assert got is not None and len(got) == 3, "minimal_repro should return three counts"
        assert got[0] == 10 and got[1] == 3, (
            f"leak_kv should give 10 rows and 3 rows with k = 'a', got {got[:2]}. "
            "Check pushFilters (EqualTo on ('k',)) and read()")
        assert got[2] == 3, (
            f"on stock 4.2.0 the third count shows the bug: expected 3 (the leaked filter), got {got[2]}. "
            "Reuse ONE DataFrame for all three queries")
        print("1. minimal repro on 4.2.0:", got, "(the last count should be 10)")

        # 2. Planning calls: the third query plans nothing
        audit = tempfile.mkdtemp(prefix="audit_")
        calls = planning_calls(spark, audit)
        assert calls == [1, 1, 0], (
            f"expected planned reads [1, 1, 0] (the third query reuses a cached read), got {calls}. "
            "Write one marker file per partitions() call into the 'audit' option's folder")
        print("2. planned reads per query:", calls)

        # 3. The reader inside the provider's cache
        df = spark.read.format(NAME).load()
        states = [provider_reader_state(df)]
        df.count()
        states.append(provider_reader_state(df))
        df.filter("k = 'a'").count()
        states.append(provider_reader_state(df))
        expected = [None, {"k": None, "audit": None}, {"k": "a", "audit": None}]
        assert states == expected, (
            f"provider_reader_state after load(), count() and filter(k = 'a').count() should be "
            f"{expected}, got {states}")
        print("3. reader state cached on the provider:", states)

        # 4. The regression tests fail on 4.2.0, as failures, and pass on fresh loads
        buggy = run_tests(spark, shared_factory(spark))
        assert len(buggy) == 3, f"LeakRegressionTests should have the three tests of the exercise, got {sorted(buggy)}"
        for name, status in buggy.items():
            assert status == "fail", (
                f"{name} should FAIL on stock 4.2.0 with a shared DataFrame (an assertion), got {status}")
        fixed = run_tests(spark, fresh_factory(spark))
        for name, status in fixed.items():
            assert status == "ok", f"{name} should pass when every make() loads afresh, got {status}"
        print("4. regression tests, shared DataFrame:", buggy)
        print("   regression tests, fresh loads:     ", fixed)

        # 5. The workaround
        safe = SafeSource(spark, NAME)
        poisoned = safe.table()
        assert poisoned is not None and hasattr(poisoned, "filter"), "SafeSource.table() should return a DataFrame"
        poisoned.filter("k = 'a'").count()
        assert safe.table().count() == 10, "SafeSource.table() should load afresh on every call"
        assert safe.table().union(safe.table().filter("k = 'a'")).count() == 13, (
            "two table() calls in one query should not share a provider")
        snap = safe.snapshot()
        assert snap is not None and hasattr(snap, "filter"), "SafeSource.snapshot() should return a DataFrame"
        assert [snap.count(), snap.filter("k = 'a'").count(), snap.count()] == [10, 3, 10], (
            "snapshot() should give 10, 3, 10")
        assert "BatchScan" not in snap.filter("k = 'a'")._jdf.queryExecution().executedPlan().toString(), (
            "queries on snapshot() should not scan the source again")
        print("5. SafeSource: fresh tables and a snapshot give correct counts")
    finally:
        spark.stop()

    # 6. The fix: compile, then rerun the tests with shared DataFrames on the patched classes
    work = tempfile.mkdtemp(prefix="patch_")
    classes = compile_patch(work)
    r = subprocess.run([sys.executable, os.path.abspath(__file__), "--patched", classes],
                       capture_output=True, text=True, timeout=300)
    lines = [l for l in r.stdout.splitlines() if l.startswith("{")]
    assert r.returncode == 0 and lines, "The patched run crashed:\n" + r.stderr[-3000:]
    patched = json.loads(lines[-1])
    assert patched["loaded_from"].rstrip("/") == classes.rstrip("/"), (
        f"PythonScanBuilder was loaded from {patched['loaded_from']}, not from your patched classes")
    assert all(s == "ok" for s in patched["tests"].values()), (
        f"With your patch the regression tests should pass on shared DataFrames, got {patched['tests']}")
    assert patched["counts"] == [10, 3, 10], f"With your patch the repro should give [10, 3, 10], got {patched['counts']}"
    assert patched["provider_state"] in (None, {"k": None, "audit": None}), (
        "After a pushed query the provider must not hold the pushed reader; "
        f"it holds {patched['provider_state']}. Keep the pushdown read info on the scan")
    print("6. patched classes from", patched["loaded_from"])
    print("   regression tests, shared DataFrame:", patched["tests"])
    print("   repro counts:", patched["counts"], "| provider state after the pushed query:", patched["provider_state"])
    print("All tests passed!")
