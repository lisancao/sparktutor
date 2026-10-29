"""
Writers - Starter Code

A tiny committed file format written by a Python data source:

- `format("jsonlog")`: each task writes JSON lines into a staging folder;
  commit() on the driver moves the files into place and records them in
  _MANIFEST.json; abort() deletes the staging folder. Overwrite removes the
  files of the previous manifest, because nothing else will.
- `format("arrowparquet")`: an Arrow writer that receives pyarrow
  RecordBatches and writes one Parquet file per task.

Input: the 200 requests in data/messy/logs/access.log, parsed into
(ip, status, path, bytes).
"""

import json
import os
import shutil
import uuid

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.datasource import (
    DataSource,
    DataSourceArrowWriter,
    DataSourceWriter,
    WriterCommitMessage,
)

MANIFEST = "_MANIFEST.json"


# ---- Helpers (given) ----
def read_manifest(root):
    """The current manifest, or an empty one if nothing was committed yet."""
    path = os.path.join(root, MANIFEST)
    if not os.path.exists(path):
        return {"files": [], "rows": 0, "commits": 0, "last_mode": None}
    with open(path) as f:
        return json.load(f)


def write_manifest(root, manifest):
    """Replace the manifest in one step: write a temp file, then rename it."""
    tmp = os.path.join(root, f".{MANIFEST}.{uuid.uuid4().hex}")
    with open(tmp, "w") as f:
        json.dump(manifest, f, indent=1)
    os.replace(tmp, os.path.join(root, MANIFEST))


class FileWritten(WriterCommitMessage):
    """What one task tells the driver: the file it staged and its row count."""

    def __init__(self, file, rows):
        self.file = file
        self.rows = rows


# ---- The JSON lines writer ----
class JsonLogDataSource(DataSource):
    @classmethod
    def name(cls):
        return "jsonlog"

    def writer(self, schema, overwrite):
        return JsonLogWriter(self.options, overwrite)


class JsonLogWriter(DataSourceWriter):
    def __init__(self, options, overwrite):
        # Runs once, on the driver. Spark pickles this object and sends a
        # copy to every task, so the job id below is the same everywhere.
        if "path" not in options:
            raise ValueError("jsonlog needs a path: .save(path) or .option('path', ...)")
        self.root = options["path"]
        self.overwrite = overwrite
        self.job = uuid.uuid4().hex[:8]
        self.staging = os.path.join(self.root, "_staging", self.job)

    def write(self, rows):
        """Runs once per task, on an executor. `rows` is an iterator of Row."""
        from pyspark import TaskContext

        task = TaskContext.get().partitionId()
        name = f"part-{task:05d}-{self.job}.jsonl"
        # TODO 1: create self.staging (os.makedirs with exist_ok=True), write
        #   each row as one JSON line (json.dumps(row.asDict())) to
        #   os.path.join(self.staging, name), count the rows, and return
        #   FileWritten(name, count). Spark refuses anything that is not a
        #   WriterCommitMessage, so always return one.
        return FileWritten(None, 0)

    def commit(self, messages):
        """Runs once, on the driver, after every task succeeded."""
        old = read_manifest(self.root)
        # TODO 2: publish the job.
        #   a. Move each staged file (m.file in self.staging) into self.root
        #      with os.replace.
        #   b. Work out the new file list and row count: on append, the old
        #      manifest's files and rows plus this job's; on overwrite, only
        #      this job's.
        #   c. write_manifest(self.root, {...}) with keys files, rows,
        #      commits (old["commits"] + 1) and last_mode ("append" or
        #      "overwrite").
        #   d. On overwrite, delete the files listed in the OLD manifest
        #      (after the new manifest is in place).
        #   e. Remove the staging folder (shutil.rmtree).
        pass

    def abort(self, messages):
        """Runs once, on the driver, if any task failed. Failed tasks send None."""
        # TODO 3: delete this job's staging folder (shutil.rmtree with
        #   ignore_errors=True), so a failed job leaves nothing behind.
        pass


# ---- The Arrow writer ----
class ArrowParquetDataSource(DataSource):
    @classmethod
    def name(cls):
        return "arrowparquet"

    def writer(self, schema, overwrite):
        return ArrowParquetWriter(self.options)


class ArrowParquetWriter(DataSourceArrowWriter):
    def __init__(self, options):
        self.root = options["path"]

    def write(self, batches):
        """`batches` is an iterator of pyarrow.RecordBatch, not of Row."""
        import pyarrow as pa
        import pyarrow.parquet as pq
        from pyspark import TaskContext

        name = f"part-{TaskContext.get().partitionId():05d}.parquet"
        # TODO 4: collect the batches into a list, count their rows
        #   (b.num_rows), and if there is at least one batch write them as
        #   one Parquet file: pq.write_table(pa.Table.from_batches(batches),
        #   os.path.join(self.root, name)) after os.makedirs(self.root,
        #   exist_ok=True). Return FileWritten(name, rows), or
        #   FileWritten(None, 0) for an empty task.
        return FileWritten(None, 0)

    def commit(self, messages):
        write_manifest(self.root, {
            "files": [m.file for m in messages if m.file],
            "rows": sum(m.rows for m in messages),
            "commits": 1,
            "last_mode": "arrow",
        })


# ---- Input data (given) ----
LOG_PATTERN = r'^(\S+) \S+ \S+ \[[^\]]+\] "GET (\S+?)(?:\?\S*)? HTTP/1\.1" (\d{3}) (\d+)'


def load_requests(spark):
    """The access log as (ip, path, status, bytes), spread over 3 tasks."""
    lines = spark.read.text("data/messy/logs/access.log")
    return lines.select(
        F.regexp_extract("value", LOG_PATTERN, 1).alias("ip"),
        F.regexp_extract("value", LOG_PATTERN, 2).alias("path"),
        F.regexp_extract("value", LOG_PATTERN, 3).cast("int").alias("status"),
        F.regexp_extract("value", LOG_PATTERN, 4).cast("long").alias("bytes"),
    ).repartition(3)


# ---- Test harness ----
if __name__ == "__main__":
    import tempfile

    spark = (SparkSession.builder
        .appName("WritersTest")
        .master("local[*]")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    spark.dataSource.register(JsonLogDataSource)
    spark.dataSource.register(ArrowParquetDataSource)

    requests = load_requests(spark).cache()
    assert requests.count() == 200, "the access log should parse into 200 requests"
    out = os.path.join(tempfile.mkdtemp(prefix="writers_"), "requests")

    def part_files():
        return sorted(f for f in os.listdir(out) if f.startswith("part-"))

    def condition(error):
        get = getattr(error, "getCondition", None)
        return get() if get else None

    def save(label, writer, path):
        """Run one write; turn a crash into a readable test failure."""
        try:
            writer.save(path)
        except Exception as e:
            lines = [l.strip() for l in str(e).splitlines() if "Error" in l or "error" in l]
            raise AssertionError(
                f"{label} failed with {condition(e) or type(e).__name__}: "
                f"{lines[-1] if lines else str(e)[:300]}") from None

    # 1. A first append: 3 tasks, 3 files, 200 rows
    save("the first append", requests.write.format("jsonlog").mode("append"), out)
    m = read_manifest(out)
    assert m["rows"] == 200, f"manifest should count 200 rows after the first append, got {m['rows']}"
    assert len(m["files"]) == 3, f"3 tasks should commit 3 files, manifest lists {len(m['files'])}"
    assert part_files() == sorted(m["files"]), (
        "commit() should move every staged file next to the manifest; "
        f"on disk: {part_files()}, in the manifest: {m['files']}")
    assert not os.listdir(os.path.join(out, "_staging")), "commit() should delete its staging folder"
    print("after append:", {k: m[k] for k in ("rows", "commits", "last_mode")}, len(m["files"]), "files")

    # 2. A second append adds to the manifest
    save("the second append", requests.write.format("jsonlog").mode("append"), out)
    m = read_manifest(out)
    assert m["rows"] == 400 and len(m["files"]) == 6, (
        f"append should keep the old files and add new ones: expected 400 rows in 6 files, "
        f"got {m['rows']} rows in {len(m['files'])} files")
    assert spark.read.json(out).count() == 400, "Spark's JSON reader should see the 400 committed rows"

    # 3. Overwrite replaces the previous files (your writer has to do it)
    save("the overwrite", requests.write.format("jsonlog").mode("overwrite"), out)
    m = read_manifest(out)
    assert m["rows"] == 200 and m["last_mode"] == "overwrite", (
        f"overwrite should leave 200 rows and record last_mode 'overwrite', got {m['rows']} and {m['last_mode']}")
    assert part_files() == sorted(m["files"]) and len(m["files"]) == 3, (
        "overwrite should delete the files of the previous manifest: "
        f"{len(part_files())} part files on disk, {len(m['files'])} in the manifest")
    print("after overwrite:", {k: m[k] for k in ("rows", "commits", "last_mode")}, len(m["files"]), "files")

    # 4. A failing job leaves the committed data alone
    broken = requests.withColumn(
        "status", F.when(F.col("path") == "/login", F.raise_error("bad row")).otherwise(F.col("status")))
    try:
        broken.write.format("jsonlog").mode("append").save(out)
        raise AssertionError("the broken write should have failed")
    except AssertionError:
        raise
    except Exception as e:
        print("failed write raised:", condition(e) or type(e).__name__)
    m = read_manifest(out)
    assert m["rows"] == 200 and len(part_files()) == 3, (
        f"a failed job must not change the table: manifest has {m['rows']} rows, "
        f"{len(part_files())} part files on disk")
    assert not os.listdir(os.path.join(out, "_staging")), (
        "abort() should delete the staging folder of the failed job")

    # 5. The default save mode is refused
    try:
        requests.write.format("jsonlog").save(out)
        raise AssertionError("the default mode (errorifexists) should be refused")
    except AssertionError:
        raise
    except Exception as e:
        assert condition(e) == "UNSUPPORTED_DATA_SOURCE_SAVE_MODE", f"unexpected error: {condition(e)}"
        print("default mode:", condition(e))

    # 6. The Arrow writer
    pq_out = os.path.join(os.path.dirname(out), "requests_parquet")
    save("the Arrow write", requests.write.format("arrowparquet").mode("append"), pq_out)
    back = spark.read.parquet(pq_out)
    am = read_manifest(pq_out)
    assert back.count() == 200 and am["rows"] == 200, (
        f"the Arrow writer should write 200 rows, Parquet has {back.count()}, manifest {am['rows']}")
    assert len(am["files"]) == 3, f"expected one Parquet file per task (3), got {am['files']}"
    by_status = {r["status"]: r["count"] for r in back.groupBy("status").count().collect()}
    assert by_status == {200: 98, 302: 24, 404: 41, 500: 37}, f"status counts changed in Parquet: {by_status}"
    back.printSchema()
    print("status counts from Parquet:", dict(sorted(by_status.items())))

    print("All tests passed!")
    spark.stop()
