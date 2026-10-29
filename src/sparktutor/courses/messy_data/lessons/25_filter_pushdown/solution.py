"""
Filter Pushdown - Solution

A Python data source over the sample data folder that pushes filters on file
metadata (kind, name, size) into file listing, so files the query does not
want are never opened. An audit log written by read() proves it.
"""

import os

from pyspark.sql import SparkSession, functions as sf
from pyspark.sql.datasource import (
    DataSource, DataSourceReader, EqualTo, GreaterThan, GreaterThanOrEqual, In,
    InputPartition, LessThan, LessThanOrEqual, StringEndsWith,
)

ROOT = "data/messy"
SCHEMA = "path string, name string, kind string, size long, width int, height int"

KINDS = {".png": "image", ".wav": "audio", ".pdf": "pdf", ".eml": "email", ".md": "text",
         ".txt": "text", ".log": "log", ".json": "json", ".xml": "xml"}


def kind_of(path):
    return KINDS.get(os.path.splitext(path)[1].lower(), "other")


def list_files(root):
    """Every file under root, sorted, as (path, size) pairs. Uses os.stat only: nothing is opened."""
    found = []
    for folder, _, names in os.walk(root):
        for n in names:
            p = os.path.join(folder, n)
            found.append((p, os.path.getsize(p)))
    return sorted(found)


class FilesPartition(InputPartition):
    def __init__(self, files):
        self.files = files


class FilesDataSource(DataSource):
    """format("files"): options path (required), partitions (default 2), audit_dir (optional)."""

    @classmethod
    def name(cls):
        return "files"

    def schema(self):
        return SCHEMA

    def reader(self, schema):
        return FilesReader(self.options)


class FilesReader(DataSourceReader):
    def __init__(self, options):
        self.root = options["path"]
        self.n = int(options.get("partitions", 2))
        self.audit_dir = options.get("audit_dir")
        self.kinds = None        # set of kinds to keep, from EqualTo / In on kind
        self.suffixes = []       # name suffixes to keep, from StringEndsWith on name
        self.size_tests = []     # (operator name, value) pairs on size

    def pushFilters(self, filters):
        """Keep the filters that can be decided from the file listing; yield the rest back to Spark."""
        for f in filters:
            if isinstance(f, EqualTo) and f.attribute == ("kind",):
                self.kinds = {f.value} if self.kinds is None else self.kinds & {f.value}
            elif isinstance(f, In) and f.attribute == ("kind",):
                self.kinds = set(f.value) if self.kinds is None else self.kinds & set(f.value)
            elif isinstance(f, StringEndsWith) and f.attribute == ("name",):
                self.suffixes.append(f.value)
            elif isinstance(f, (GreaterThan, GreaterThanOrEqual, LessThan, LessThanOrEqual)) \
                    and f.attribute == ("size",):
                self.size_tests.append((type(f).__name__, f.value))
            else:
                yield f

    def matches(self, path, size):
        """True if a file passes every filter this reader took over from Spark."""
        if self.kinds is not None and kind_of(path) not in self.kinds:
            return False
        name = os.path.basename(path)
        if any(not name.endswith(s) for s in self.suffixes):
            return False
        for op, value in self.size_tests:
            ok = {"GreaterThan": size > value, "GreaterThanOrEqual": size >= value,
                  "LessThan": size < value, "LessThanOrEqual": size <= value}[op]
            if not ok:
                return False
        return True

    def partitions(self):
        files = [p for p, size in list_files(self.root) if self.matches(p, size)]
        groups = [files[i::self.n] for i in range(self.n)]
        return [FilesPartition(g) for g in groups if g] or [FilesPartition([])]

    def read(self, partition):
        import struct
        import uuid

        opened = []
        for path in partition.files:
            with open(path, "rb") as f:
                head = f.read(24)
            opened.append(path)
            width = height = None
            if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
                width, height = struct.unpack(">II", head[16:24])
            yield (path, os.path.basename(path), kind_of(path), os.path.getsize(path), width, height)
        if self.audit_dir:
            with open(os.path.join(self.audit_dir, f"{uuid.uuid4().hex}.log"), "w") as log:
                log.write("".join(p + "\n" for p in opened))


# ---- Test harness ----
if __name__ == "__main__":
    import contextlib
    import io
    import shutil
    import tempfile

    spark = (SparkSession.builder
        .appName("FilterPushdown")
        .master("local[*]")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    # The lesson's counts cover the course's original sample folders. data/messy
    # has grown other folders for later lessons, so copy just these into a scratch
    # folder and point the source there. The path is absolute: on Spark Connect
    # the Python workers run in a per-session directory.
    root = tempfile.mkdtemp(prefix="pushdown_input_")
    for folder in ["audio", "docs", "events", "images", "logs", "mail", "pdf", "xml"]:
        shutil.copytree(os.path.abspath(os.path.join(ROOT, folder)), os.path.join(root, folder))
    all_files = list_files(root)

    def run(condition):
        """Rows, opened file names and the plan's Filter lines for a query on the source."""
        audit = tempfile.mkdtemp(prefix="audit_")
        df = (spark.read.format("files").option("path", root).option("audit_dir", audit).load()
            .filter(condition))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            df.explain()
        filters = [l.strip() for l in buf.getvalue().splitlines() if "Filter" in l and "Scan" not in l]
        rows = df.collect()
        opened = sorted(os.path.basename(line.strip())
                        for name in os.listdir(audit) for line in open(os.path.join(audit, name)))
        return rows, opened, filters

    def names(rows):
        return sorted(r.name for r in rows)

    try:
        spark.dataSource.register(FilesDataSource)

        # 1. With the flag off (the 4.2.0 default), a reader that implements pushFilters fails
        spark.conf.set("spark.sql.python.filterPushdown.enabled", "false")
        try:
            spark.read.format("files").option("path", root).load().count()
            raise AssertionError("Expected DATA_SOURCE_PUSHDOWN_DISABLED with the flag off")
        except AssertionError:
            raise
        except Exception as e:
            assert "DATA_SOURCE_PUSHDOWN_DISABLED" in str(e), f"Unexpected error with the flag off: {str(e)[:300]}"
        spark.conf.set("spark.sql.python.filterPushdown.enabled", "true")

        # 2. kind = 'image': only the PNGs are listed and opened, and Spark drops its own check
        rows, opened, filters = run(sf.col("kind") == "image")
        pngs = sorted(os.path.basename(p) for p, _ in all_files if p.endswith(".png"))
        assert names(rows) == pngs, (
            f"kind = 'image' should return the PNGs {pngs}, got {names(rows)}. A filter you take over "
            "in pushFilters is no longer checked by Spark, so matches() must apply it")
        assert opened == pngs, (
            f"Only the PNGs should be opened, but read() opened {opened}. "
            "Handle EqualTo on kind in pushFilters and apply it in partitions()")
        assert not any("image" in l for l in filters), (
            f"Spark should no longer evaluate kind = 'image' itself, but the plan has {filters}. "
            "Do not yield the EqualTo filter you handled")

        # 3. kind IN (...)
        rows, opened, filters = run(sf.col("kind").isin("audio", "pdf"))
        want = sorted(os.path.basename(p) for p, _ in all_files if p.endswith((".wav", ".pdf")))
        assert names(rows) == want and opened == want, (
            f"kind IN ('audio', 'pdf') should list and open only {want}; rows {names(rows)}, opened {opened}")

        # 4. name LIKE '%.eml' arrives as StringEndsWith
        rows, opened, filters = run(sf.col("name").endswith(".eml"))
        want = sorted(os.path.basename(p) for p, _ in all_files if p.endswith(".eml"))
        assert names(rows) == want and opened == want, (
            f"name ending in .eml should list and open only {want}; rows {names(rows)}, opened {opened}")

        # 5. size > 4000 is decided from os.stat, before any file is opened
        rows, opened, filters = run(sf.col("size") > 4000)
        want = sorted(os.path.basename(p) for p, s in all_files if s > 4000)
        assert names(rows) == want and opened == want, (
            f"size > 4000 should list and open only {want}; rows {names(rows)}, opened {opened}")
        assert not any("4000" in l for l in filters), f"size > 4000 should be pushed, plan has {filters}"

        # 6. width needs the file's bytes: Spark keeps that part, the reader keeps the kind part
        rows, opened, filters = run((sf.col("kind") == "image") & (sf.col("width") > 12))
        filters_mixed = filters
        assert names(rows) == ["gradient_32x32.png", "gray_20x10.png", "red_16x8.png"], (
            f"Expected the three PNGs wider than 12 pixels, got {names(rows)}")
        assert opened == pngs, f"Every PNG has to be opened to read its width, opened {opened}"
        assert any("width" in l and "12" in l for l in filters), f"width > 12 should stay in Spark's Filter: {filters}"

        # 7. An OR across columns is not pushed at all, and the answer is still right
        rows, opened, filters = run((sf.col("kind") == "audio") | (sf.col("size") < 100))
        want = sorted(os.path.basename(p) for p, s in all_files if p.endswith(".wav") or s < 100)
        assert names(rows) == want, f"kind = 'audio' OR size < 100 should return {want}, got {names(rows)}"
        assert len(opened) == len(all_files), "An OR is not pushed, so every file is opened"

        # 8. The 4.2.0 trap from the lesson: reusing a DataFrame after a pushed-down query
        reused = spark.read.format("files").option("path", root).load()
        reused.filter(sf.col("kind") == "image").count()
        stale = reused.count()
        fresh = spark.read.format("files").option("path", root).load().count()
        assert fresh == len(all_files), f"A fresh load() should see all {len(all_files)} files, got {fresh}"

        print(f"kind = 'image' opened {len(pngs)} of {len(all_files)} files")
        print(f"Same DataFrame counted again after a pushed filter: {stale} rows; fresh load(): {fresh} rows")
        print("Spark's remaining Filter for kind = 'image' AND width > 12:")
        for line in filters_mixed:
            print("  ", line)
        (spark.read.format("files").option("path", root).load()
            .filter(sf.col("kind").isin("image", "audio"))
            .select("name", "kind", "size", "width", "height").orderBy("kind", "name").show(truncate=False))
        print("All tests passed!")
    finally:
        spark.stop()
