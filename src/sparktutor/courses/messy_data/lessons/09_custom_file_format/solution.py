"""
Reading a Custom File Format, in Parallel - Solution

A "docs" data source: spark.read.format("docs").option("path", folder).load()
returns one row per file under the folder, with metadata and a few fields
parsed from the file's own header bytes (PNG size, WAV duration).

Options (strings, case-insensitive keys):
  path        required: an existing folder
  glob        optional, default "**/*" (every file, recursively)
  partitions  optional, default 2: how many parallel tasks at most

Pieces:
1. kind_of, list_files, plan_files: plain Python helpers (the driver side)
2. png_size, wav_seconds: parse the header of one file (the executor side)
3. FilesPartition: the files one task reads
4. DocsDataSource and DocsReader: the data source itself
"""

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.datasource import CaseInsensitiveDict, DataSource, DataSourceReader, InputPartition
from pyspark.sql.types import (
    DoubleType, IntegerType, LongType, StringType, StructField, StructType, TimestampType,
)

SCHEMA = ("path string, name string, kind string, size long, modified timestamp, "
          "width int, height int, seconds double")

SCHEMA_STRUCT = StructType([
    StructField("path", StringType()), StructField("name", StringType()),
    StructField("kind", StringType()), StructField("size", LongType()),
    StructField("modified", TimestampType()), StructField("width", IntegerType()),
    StructField("height", IntegerType()), StructField("seconds", DoubleType()),
])

KINDS = {".png": "image", ".wav": "audio", ".pdf": "pdf", ".eml": "email", ".md": "text",
         ".txt": "text", ".log": "log", ".json": "json", ".xml": "xml"}

# Columns that need the file's bytes; the others come from the file system alone
HEADER_COLUMNS = {"width", "height", "seconds"}


def kind_of(path):
    """The kind of a file, from its extension (cheap: no need to open it)."""
    import os

    return KINDS.get(os.path.splitext(path)[1].lower(), "other")


def list_files(root, pattern):
    """(absolute path, size) of every file under root matching pattern, sorted by path."""
    from pathlib import Path

    return sorted((str(p.resolve()), p.stat().st_size) for p in Path(root).glob(pattern) if p.is_file())


def plan_files(files, n):
    """Assign (path, size) pairs to at most n groups with similar total size.

    Largest file first, each into the group with the smallest total so far
    (ties go to the lowest group number). Empty groups are dropped.
    """
    groups = [[] for _ in range(max(n, 1))]
    totals = [0] * len(groups)
    for path, size in sorted(files, key=lambda f: (-f[1], f[0])):
        i = totals.index(min(totals))
        groups[i].append(path)
        totals[i] += size
    return [g for g in groups if g]


def png_size(head):
    """(width, height) from the first 24 bytes of a PNG, or (None, None)."""
    import struct

    if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR" and len(head) >= 24:
        return struct.unpack(">II", head[16:24])
    return None, None


def wav_seconds(path):
    """Duration of a WAV file from its header, or None if it is not a readable WAV."""
    import wave

    try:
        with wave.open(path) as w:
            return w.getnframes() / w.getframerate()
    except (wave.Error, EOFError, ZeroDivisionError):
        return None


def describe(path, wanted):
    """A dict with every column for one file. Opens the file only if `wanted` needs it."""
    import datetime
    import os

    st = os.stat(path)
    row = {"path": path, "name": os.path.basename(path), "kind": kind_of(path), "size": st.st_size,
           "modified": datetime.datetime.fromtimestamp(st.st_mtime, tz=datetime.timezone.utc),
           "width": None, "height": None, "seconds": None}
    if wanted & HEADER_COLUMNS:
        if row["kind"] == "image":
            with open(path, "rb") as f:
                row["width"], row["height"] = png_size(f.read(24))
        elif row["kind"] == "audio":
            row["seconds"] = wav_seconds(path)
    return row


class FilesPartition(InputPartition):
    """The files (absolute paths) that one task reads."""

    def __init__(self, files):
        self.files = files


class DocsDataSource(DataSource):
    """format("docs"): one row per file in a folder."""

    @classmethod
    def name(cls):
        return "docs"

    def schema(self):
        return SCHEMA

    def reader(self, schema):
        return DocsReader(self.options, schema)


class DocsReader(DataSourceReader):
    def __init__(self, options, schema):
        import os

        if "path" not in options:
            raise ValueError("option 'path' is required: the folder to read")
        # Resolve now, while planning: tasks may run with another working directory
        self.root = os.path.abspath(options["path"])
        if not os.path.isdir(self.root):
            raise ValueError(f"option 'path' must be an existing folder, got {options['path']!r}")
        self.pattern = options.get("glob", "**/*")
        try:
            self.max_partitions = int(options.get("partitions", "2"))
        except ValueError:
            raise ValueError(f"option 'partitions' must be a whole number, got {options['partitions']!r}") from None
        if self.max_partitions < 1:
            raise ValueError(f"option 'partitions' must be >= 1, got {self.max_partitions}")
        self.columns = [f.name for f in schema.fields]
        known = [f.name for f in SCHEMA_STRUCT.fields]
        unknown = [c for c in self.columns if c not in known]
        if unknown:
            raise ValueError(f"docs has no column(s) {unknown}; available: {', '.join(known)}")

    def partitions(self):
        # Runs once, during planning: list the folder and share out the files.
        # Only paths travel to the tasks, never file contents.
        files = list_files(self.root, self.pattern)
        return [FilesPartition(group) for group in plan_files(files, self.max_partitions)]

    def read(self, partition):
        if not isinstance(partition, FilesPartition):
            return  # no files were planned: Spark sends InputPartition(None)
        wanted = set(self.columns)
        for path in partition.files:
            row = describe(path, wanted)
            yield tuple(row[c] for c in self.columns)


# ---- Test harness ----
if __name__ == "__main__":
    import os
    import pickle
    import tempfile

    # 1. Plain Python, before any Spark session exists
    got = plan_files([("a", 5), ("b", 4), ("c", 3), ("d", 3)], 2)
    assert got == [["a", "d"], ["b", "c"]], (
        f"plan_files([('a', 5), ('b', 4), ('c', 3), ('d', 3)], 2) should be [['a', 'd'], ['b', 'c']], got {got}")
    assert plan_files([("a", 1)], 4) == [["a"]], "plan_files should drop empty groups"
    assert plan_files([], 3) == [], "plan_files of no files should be []"
    assert kind_of("x/Photo.PNG") == "image" and kind_of("notes") == "other", "kind_of should ignore case and default to other"

    red = open("data/messy/images/products/red_16x8.png", "rb").read(24)
    assert png_size(red) == (16, 8), f"png_size of red_16x8.png should be (16, 8), got {png_size(red)}"
    assert png_size(open("data/messy/images/scans/corrupt.png", "rb").read(24)) == (None, None), (
        "corrupt.png has no IHDR chunk: png_size should return (None, None)")
    assert wav_seconds("data/messy/audio/silence.wav") == 0.5, "silence.wav lasts 0.5 s"
    assert wav_seconds("data/messy/mail/ticket_0.eml") is None, "wav_seconds should return None for a non-WAV file"

    reader = DocsReader(CaseInsensitiveDict({"path": "data/messy/audio"}), SCHEMA_STRUCT)
    parts = reader.partitions()
    assert [len(p.files) for p in parts] == [1, 2], (
        f"3 WAV files in 2 partitions: silence.wav (8044 bytes) alone, the two tones together; "
        f"got {[p.files for p in parts]}")
    rows = [r for p in parts for r in reader.read(p)]
    assert sorted((r[1], r[7]) for r in rows) == [("silence.wav", 0.5), ("tone_440.wav", 0.25), ("tone_880_quiet.wav", 0.25)], (
        f"Reading the audio folder without Spark gave {rows}")
    pickle.loads(pickle.dumps(reader))
    pickle.loads(pickle.dumps(parts))
    print("Plain Python tests passed (no Spark session needed)")

    # 2. Through Spark
    spark = (SparkSession.builder
             .appName("CustomFileFormat")
             .master("local[*]")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    try:
        spark.dataSource.register(DocsDataSource)
        # Pass absolute paths: the reader may plan in a process whose working
        # directory is not this script's (on Spark Connect it never is)
        data = os.path.abspath("data/messy")
        total_files = sum(len(files) for _, _, files in os.walk(data))

        df = spark.read.format("docs").option("path", data).option("partitions", 3).load()
        assert df.columns == [f.name for f in SCHEMA_STRUCT.fields], f"Columns should follow SCHEMA, got {df.columns}"
        df = df.cache()
        assert df.count() == total_files, f"Expected one row per file ({total_files}), got {df.count()}"
        tasks = df.select(F.spark_partition_id()).distinct().count()
        assert tasks == 3, f"option partitions 3 should give 3 partitions, got {tasks}"
        per_task = [r["b"] for r in df.groupBy(F.spark_partition_id().alias("p")).agg(F.sum("size").alias("b")).collect()]
        largest = df.agg(F.max("size")).first()[0]
        assert max(per_task) - min(per_task) <= largest, (
            f"Partitions should hold similar byte totals (plan_files), got {sorted(per_task)}")

        kinds = {r["kind"]: r["n"] for r in df.groupBy("kind").agg(F.count("*").alias("n")).collect()}
        for kind, n in {"image": 5, "audio": 3, "pdf": 2, "email": 4}.items():
            assert kinds.get(kind) == n, f"Expected {n} files of kind {kind}, got {kinds.get(kind)} ({kinds})"
        assert kinds.get("text", 0) >= 6, f"The .md and .txt files are kind text, got {kinds}"

        by_name = {r["name"]: r for r in df.collect()}
        assert (by_name["gradient_32x32.png"]["width"], by_name["gradient_32x32.png"]["height"]) == (32, 32), (
            "gradient_32x32.png should be 32 x 32")
        assert by_name["corrupt.png"]["kind"] == "image" and by_name["corrupt.png"]["width"] is None, (
            "corrupt.png is kind image (by extension) but has no readable width")
        assert by_name["tone_440.wav"]["seconds"] == 0.25, "tone_440.wav lasts 0.25 s"
        assert by_name["app.log"]["size"] == os.path.getsize("data/messy/logs/app.log"), "size should be the file size in bytes"
        assert by_name["app.log"]["path"].startswith("/"), "path should be absolute (resolve it while planning)"
        assert by_name["app.log"]["modified"] is not None, "modified should come from the file's modification time"

        meta = spark.read.format("docs").schema("path string, kind string, size long").option("path", f"{data}/pdf").load()
        assert meta.columns == ["path", "kind", "size"], f"A user schema should give only its columns, got {meta.columns}"
        assert sorted(r["size"] for r in meta.collect()) == [603, 878], "pdf/ holds two PDFs of 603 and 878 bytes"

        only_png = (spark.read.format("docs").option("path", f"{data}/images").option("glob", "**/*.png").load())
        assert only_png.count() == 5, f"glob **/*.png under images/ should match 5 files, got {only_png.count()}"

        empty = tempfile.mkdtemp(prefix="empty_")
        assert spark.read.format("docs").option("path", empty).load().count() == 0, (
            "An empty folder should give 0 rows (read() gets InputPartition(None) and must yield nothing)")

        for options, words in [({}, "option 'path' is required"),
                               ({"path": f"{data}/nope"}, "existing folder"),
                               ({"path": data, "partitions": "many"}, "whole number")]:
            reader_df = spark.read.format("docs")
            for k, v in options.items():
                reader_df = reader_df.option(k, v)
            try:
                reader_df.load().count()
            except Exception as e:  # noqa: BLE001
                assert words in str(e), f"Options {options} should fail with a message containing {words!r}; got {str(e)[:300]}"
            else:
                raise AssertionError(f"Options {options} should fail")

        print("Files per partition:")
        (df.groupBy(F.spark_partition_id().alias("partition"))
           .agg(F.count("*").alias("files"), F.sum("size").alias("bytes"))
           .orderBy("partition").show())
        df.select("name", "kind", "size", "width", "height", "seconds").orderBy("kind", "name").show(30)
        print("All tests passed!")
    finally:
        spark.stop()
