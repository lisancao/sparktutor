"""
Capstone, part 1: An Unstructured Ingestion Source - Starter Code

`format("docs")` reads a folder of mixed files and returns one row per
document part, parsed with the Python standard library only:

    kind    one row per            filled columns
    image   file (PNG)             width, height (NULL if the file is not a PNG)
    audio   file (WAV)             seconds
    pdf     page                   part (1, 2, ...), text
    email   file (.eml)            title (subject), text (body)
    text, log, json, xml           title (first line), text

Every row also has path, kind, part, size and sha256. Filters on `kind`
are pushed into the file listing, so files of other kinds are never
opened. The same source streams: new files in a folder become new rows,
at most maxFilesPerTrigger files per micro-batch.
"""

import os

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.datasource import (
    DataSource,
    DataSourceReader,
    DataSourceStreamReader,
    EqualTo,
    In,
    InputPartition,
)
from pyspark.sql.streaming.datasource import (
    ReadAllAvailable,
    ReadMaxFiles,
    SupportsTriggerAvailableNow,
)

SCHEMA = ("path string, kind string, part int, size long, sha256 string, "
          "width int, height int, seconds double, title string, text string")

KINDS = {".png": "image", ".wav": "audio", ".pdf": "pdf", ".eml": "email",
         ".md": "text", ".txt": "text", ".log": "log", ".json": "json", ".xml": "xml"}

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def kind_of(path):
    return KINDS.get(os.path.splitext(path)[1].lower(), "other")


# ---- Parsing one file into parts (runs on executors) ----
def parse_file(path):
    """Yield one dict per part of the file at `path`."""
    import hashlib
    import io
    import re
    import struct
    import wave
    from email import policy
    from email.parser import BytesParser

    with open(path, "rb") as f:
        data = f.read()
    base = {"path": path, "kind": kind_of(path), "part": 0, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "width": None, "height": None,
            "seconds": None, "title": None, "text": None}
    kind = base["kind"]

    if kind == "image":
        # TODO 1: if data starts with PNG_MAGIC and data[12:16] == b"IHDR",
        #   set base["width"], base["height"] from struct.unpack(">II", data[16:24]).
        #   Anything else (corrupt.png) keeps NULL width and height.
        yield base

    elif kind == "audio":
        # TODO 2: open the bytes with wave.open(io.BytesIO(data)) and set
        #   base["seconds"] = frames / frame rate.
        yield base

    elif kind == "pdf":
        # TODO 3: one part per page. The pages' text is in
        #   re.findall(rb"BT .*?\((.*?)\) Tj ET", data, re.S); yield
        #   {**base, "part": n, "text": text.decode("latin-1")} with n = 1, 2, ...
        #   (this regex only works for the course's tiny uncompressed PDFs).
        yield base

    elif kind == "email":
        # TODO 4: parse with BytesParser(policy=policy.default).parsebytes(data);
        #   title = str(msg["Subject"]), text = the plain body
        #   (msg.get_body(("plain",)).get_content().strip()).
        yield base

    elif kind in ("text", "log", "json", "xml"):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")   # notes_latin1.txt, as in "Text and Logs"
        first = text.splitlines()[0] if text else ""
        yield {**base, "title": first.lstrip("# ").strip() or None, "text": text}

    else:
        yield base


def to_row(part, schema):
    return tuple(part.get(field.name) for field in schema.fields)


def list_files(root, pattern):
    from pathlib import Path
    return sorted(str(p) for p in Path(root).glob(pattern) if p.is_file())


class FilesPartition(InputPartition):
    def __init__(self, files):
        self.files = files


# ---- The source ----
class DocsDataSource(DataSource):
    @classmethod
    def name(cls):
        return "docs"

    def schema(self):
        return SCHEMA

    def reader(self, schema):
        return DocsReader(self.options, schema)

    def streamReader(self, schema):
        return DocsStreamReader(self.options, schema)


class DocsReader(DataSourceReader):
    def __init__(self, options, schema):
        if "path" not in options:
            raise ValueError("docs needs a folder: .load(path)")
        self.root = options["path"]
        self.pattern = options.get("glob", "**/*")
        self.n = int(options.get("partitions", 3))
        self.schema = schema
        self.kinds = None    # set by pushFilters

    def pushFilters(self, filters):
        # TODO 5: for EqualTo or In on the attribute ("kind",), remember the
        #   wanted kinds in self.kinds (a set) and do not yield the filter.
        #   Yield every other filter, so Spark keeps applying it.
        for f in filters:
            yield f

    def partitions(self):
        files = list_files(self.root, self.pattern)
        # TODO 6: keep only files whose kind_of(p) is in self.kinds (when it
        #   is set), then deal them round-robin into self.n groups
        #   (files[i::self.n]) and return one FilesPartition per non-empty
        #   group, or [FilesPartition([])] if there are no files.
        return [FilesPartition(files)]

    def read(self, partition):
        for path in partition.files:
            for part in parse_file(path):
                yield to_row(part, self.schema)


class DocsStreamReader(DataSourceStreamReader, SupportsTriggerAvailableNow):
    """New files in a folder, keyed by (mtime_ns, path), as in "Streaming Readers and Writers" (given)."""

    def __init__(self, options, schema):
        self.root = options["path"]
        self.max_files = int(options.get("maxFilesPerTrigger", 2))
        self.schema = schema
        self.target = None

    def _keys(self):
        return sorted((os.stat(p).st_mtime_ns, p) for p in list_files(self.root, "*"))

    def initialOffset(self):
        return {"v": 1, "mtime_ns": 0, "path": ""}

    def getDefaultReadLimit(self):
        return ReadMaxFiles(self.max_files)

    def prepareForTriggerAvailableNow(self):
        keys = self._keys()
        self.target = keys[-1] if keys else (0, "")

    def latestOffset(self, start, limit):
        new = [k for k in self._keys() if k > (start["mtime_ns"], start["path"])]
        if self.target is not None:
            new = [k for k in new if k <= self.target]
        if not isinstance(limit, ReadAllAvailable):
            new = new[:limit.max_files]
        return {"v": 1, "mtime_ns": new[-1][0], "path": new[-1][1]} if new else start

    def partitions(self, start, end):
        lo, hi = (start["mtime_ns"], start["path"]), (end["mtime_ns"], end["path"])
        return [FilesPartition([p]) for (m, p) in self._keys() if lo < (m, p) <= hi]

    def read(self, partition):
        for path in partition.files:
            for part in parse_file(path):
                yield to_row(part, self.schema)


# ---- Test harness ----
CATALOG_FOLDERS = ["audio", "docs", "events", "images", "logs", "mail", "pdf", "xml"]


if __name__ == "__main__":
    import contextlib
    import io
    import shutil
    import tempfile

    spark = (SparkSession.builder
        .appName("CapstoneSourceTest")
        .master("local[*]")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.python.filterPushdown.enabled", "true")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    spark.dataSource.register(DocsDataSource)

    # The catalog covers the course's original sample folders. data/messy has
    # grown other folders for later lessons, so copy just these into a scratch
    # folder and point the source there.
    ROOT = tempfile.mkdtemp(prefix="capstone_input_")
    for folder in CATALOG_FOLDERS:
        shutil.copytree(os.path.abspath(os.path.join("data/messy", folder)),
                        os.path.join(ROOT, folder))
    docs = spark.read.format("docs").option("path", ROOT).load().cache()

    def name(col="path"):
        return F.element_at(F.split(col, "/"), -1)

    # 1. Every file, every part
    parts, files = docs.count(), docs.select("path").distinct().count()
    assert (parts, files) == (27, 26), (
        f"expected 27 parts from 26 files, got {parts} parts from {files} files "
        "(each PDF page is a part of its own)")
    by_kind = {r["kind"]: r["count"] for r in docs.groupBy("kind").count().collect()}
    expected_kinds = {"audio": 3, "email": 4, "image": 5, "json": 3, "log": 2, "pdf": 3, "text": 6, "xml": 1}
    assert by_kind == expected_kinds, f"parts per kind: expected {expected_kinds}, got {by_kind}"
    docs.groupBy("kind").agg(F.count("*").alias("parts"), F.count_distinct("path").alias("files")) \
        .orderBy("kind").show()

    # 2. Per-kind parsing
    images = {r["f"]: (r["width"], r["height"]) for r in
              docs.filter("kind = 'image'").select(name().alias("f"), "width", "height").collect()}
    assert images == {"red_16x8.png": (16, 8), "gradient_32x32.png": (32, 32),
                      "logo_rgba_12x12.png": (12, 12), "gray_20x10.png": (20, 10),
                      "corrupt.png": (None, None)}, f"PNG sizes from IHDR are wrong: {images}"
    seconds = {r["f"]: r["seconds"] for r in
               docs.filter("kind = 'audio'").select(name().alias("f"), "seconds").collect()}
    assert seconds == {"tone_440.wav": 0.25, "tone_880_quiet.wav": 0.25, "silence.wav": 0.5}, \
        f"WAV durations are wrong: {seconds}"
    pages = sorted((r["f"], r["part"], r["text"]) for r in
                   docs.filter("kind = 'pdf'").select(name().alias("f"), "part", "text").collect())
    assert pages == [("invoice_1001.pdf", 1, "Invoice 1001 total 42.50 CAD"),
                     ("invoice_1001.pdf", 2, "Thank you for shopping"),
                     ("invoice_1002.pdf", 1, "Invoice 1002 total 17.00 CAD")], f"PDF pages are wrong: {pages}"
    emails = docs.filter("kind = 'email'")
    assert emails.filter("title IS NULL OR text NOT LIKE 'Hello, order 10%'").count() == 0, \
        "every e-mail should have its subject as title and its body as text"
    latin = docs.filter(name() == "notes_latin1.txt").first()
    assert latin["text"].startswith("Café crème"), f"notes_latin1.txt should decode as Latin-1: {latin['text']!r}"
    print("images:", images)
    print("audio seconds:", seconds)
    print("pdf pages:", pages)

    # 3. Pushdown: the kind filter never reaches Spark's Filter node
    pushed = spark.read.format("docs").option("path", ROOT).load().filter(F.col("kind").isin("pdf", "audio"))
    plan = io.StringIO()
    with contextlib.redirect_stdout(plan):
        pushed.explain()
    filter_lines = [line.strip() for line in plan.getvalue().splitlines()
                    if "Filter" in line and "BatchScan" not in line]
    assert pushed.count() == 6, f"kind IN ('pdf', 'audio') should give 3 pages + 3 WAV files, got {pushed.count()}"
    assert not any("kind" in line for line in filter_lines), (
        f"the kind filter should be pushed into the source, but Spark still filters on it: {filter_lines}")
    print("filters left after pushdown:", filter_lines or "none")

    # 4. Streaming over an inbox: 3 files arrive, then 2 more
    base = tempfile.mkdtemp(prefix="capstone_")
    inbox, out, ckpt = (os.path.join(base, d) for d in ("inbox", "catalog_stream", "checkpoint"))
    os.makedirs(inbox)
    arrivals = ["pdf/invoice_1001.pdf", "mail/ticket_0.eml", "images/products/red_16x8.png",
                "audio/silence.wav", "docs/shipping.md"]

    def arrive(i):
        dst = os.path.join(inbox, os.path.basename(arrivals[i]))
        shutil.copy(os.path.join(ROOT, arrivals[i]), dst)
        t = 1_790_000_000_000_000_000 + i * 1_000_000_000
        os.utime(dst, ns=(t, t))

    def run_stream():
        q = (spark.readStream.format("docs").option("path", inbox).option("maxFilesPerTrigger", 2).load()
             .writeStream.format("parquet").option("path", out).option("checkpointLocation", ckpt)
             .trigger(availableNow=True).start())
        q.awaitTermination()
        return [p.numInputRows for p in q.recentProgress if p.numInputRows]

    for i in range(3):
        arrive(i)
    first = run_stream()
    for i in range(3, 5):
        arrive(i)
    second = run_stream()
    print("stream batches (rows):", first, second)
    assert first == [3, 1] and second == [2], (
        f"expected batches [3, 1] then [2] (the PDF has 2 pages), got {first} and {second}")
    streamed = spark.read.parquet(out)
    assert streamed.count() == 6 and streamed.select("path").distinct().count() == 5, \
        "the streamed catalog should hold 6 parts from 5 files"

    # 5. Hand-off: the catalog as Parquet, the input a downstream pipeline would read
    catalog_path = os.path.join(base, "catalog")
    docs.drop("text").write.mode("overwrite").parquet(catalog_path)
    assert spark.read.parquet(catalog_path).count() == 27, "the Parquet catalog should hold 27 parts"
    print("catalog written:", catalog_path)

    print("All tests passed!")
    spark.stop()
