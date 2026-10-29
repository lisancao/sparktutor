"""
Memory, Spill and Very Large Files - Solution

A Python data source that reads very large line-oriented files in byte-range
chunks, so no task ever holds a whole file. Each partition is a
(path, offset, length) triple; read() streams the lines whose first byte lies
inside its range, using the same boundary rule as Hadoop's LineRecordReader.
"""

import contextlib
import io
import json
import os
import random
import shutil
import tempfile
import zlib

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.datasource import DataSource, DataSourceReader, InputPartition

SCHEMA = "path string, line_offset long, line string"


# ---------------------------------------------------------------------------
# Part 1: plan byte-range chunks (pure Python, runs on the driver)
# ---------------------------------------------------------------------------

def plan_chunks(files, chunk_bytes):
    """files: list of (path, size). Return (path, offset, length) triples that
    cover every byte of every file exactly once, in order. An empty file gets
    no chunk; the last chunk of a file may be shorter than chunk_bytes."""
    chunks = []
    for path, size in files:
        for offset in range(0, size, chunk_bytes):
            chunks.append((path, offset, min(chunk_bytes, size - offset)))
    return chunks


# ---------------------------------------------------------------------------
# Part 2: read the lines of one chunk (pure Python, runs in a Python worker)
# ---------------------------------------------------------------------------

def read_chunk_lines(f, offset, length):
    """f: a binary file object opened on the whole file.

    Yield (line_offset, line_bytes_without_newline) for every line whose
    FIRST byte lies in [offset, offset + length). A line may end past the
    chunk; the line that starts exactly at offset + length belongs to the
    next chunk. Afterwards f.tell() is how far this chunk had to read.
    """
    end = offset + length
    if offset == 0:
        f.seek(0)
    else:
        # Look at the byte just before the chunk. readline() from there
        # consumes the rest of the line that started in the previous chunk
        # (or only that one byte, if it is a newline and a line starts here).
        f.seek(offset - 1)
        f.readline()
    pos = f.tell()
    while pos < end:
        line = f.readline()
        if not line:
            break
        yield pos, line.rstrip(b"\n")
        pos += len(line)


# ---------------------------------------------------------------------------
# The data source (given)
# ---------------------------------------------------------------------------

class ChunkPartition(InputPartition):
    def __init__(self, path, offset, length):
        self.path, self.offset, self.length = path, offset, length


class ChunkedLinesReader(DataSourceReader):
    def __init__(self, options):
        self.root = options["path"]
        self.chunk_bytes = int(options.get("chunk_bytes", 8 * 1024 * 1024))
        self.audit_dir = options.get("audit_dir")

    def partitions(self):
        files = []
        for name in sorted(os.listdir(self.root)):
            p = os.path.join(self.root, name)
            if os.path.isfile(p):
                files.append((p, os.path.getsize(p)))
        return [ChunkPartition(*c) for c in plan_chunks(files, self.chunk_bytes)]

    def read(self, partition):
        # A 1 MiB read buffer: memory per task is the buffer plus one line,
        # whatever the size of the file.
        with open(partition.path, "rb", buffering=1024 * 1024) as f:
            for line_offset, line in read_chunk_lines(f, partition.offset, partition.length):
                yield (partition.path, line_offset, line.decode("utf-8"))
            consumed = f.tell() - partition.offset
        if self.audit_dir:
            name = f"{os.path.basename(partition.path)}@{partition.offset}.json"
            with open(os.path.join(self.audit_dir, name), "w") as out:
                json.dump({"offset": partition.offset, "length": partition.length,
                           "consumed": consumed}, out)


class ChunkedLines(DataSource):
    """format("chunked_lines"): options path (a folder), chunk_bytes, audit_dir."""

    @classmethod
    def name(cls):
        return "chunked_lines"

    def schema(self):
        return SCHEMA

    def reader(self, schema):
        return ChunkedLinesReader(self.options)


# ---------------------------------------------------------------------------
# Part 3: an inventory of blobs that never opens them (binaryFile)
# ---------------------------------------------------------------------------

def blob_inventory(spark, folder):
    """A binaryFile DataFrame with only path and length. Because content is
    not selected, it is not in the scan's ReadSchema and no file is opened."""
    return spark.read.format("binaryFile").load(folder).select("path", "length")


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

def make_files(root):
    """A large log of lines with random lengths, plus three edge cases."""
    rng = random.Random(41)
    os.makedirs(root)
    words = ["GET", "POST", "/api/orders", "/cart", "user=", "sku=P", "ms=", "ok", "retry", "é"]
    with open(os.path.join(root, "big.log"), "wb", buffering=1 << 20) as f:
        for i in range(260_000):
            n = rng.randint(1, 40)
            f.write((f"{i:07d} " + " ".join(rng.choice(words) for _ in range(n)) + "\n").encode())
    with open(os.path.join(root, "no_trailing_newline.log"), "wb") as f:
        f.write(b"first\nsecond\nthird-without-newline")
    open(os.path.join(root, "empty.log"), "wb").close()
    with open(os.path.join(root, "tiny.log"), "wb") as f:
        f.write(b"one line\n")


def reference(root):
    """Line count, sum of CRC32 of the lines, and the longest line, streamed."""
    count, crc_sum, longest = 0, 0, 0
    for name in sorted(os.listdir(root)):
        with open(os.path.join(root, name), "rb") as f:
            for line in f:
                count += 1
                crc_sum += zlib.crc32(line.rstrip(b"\n"))
                longest = max(longest, len(line))
    return count, crc_sum, longest


def plan_text(df, mode="formatted"):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        df.explain(mode)
    return buf.getvalue()


if __name__ == "__main__":
    tmp = tempfile.mkdtemp()
    root = os.path.join(tmp, "logs")
    audit = os.path.join(tmp, "audit")
    os.makedirs(audit)
    make_files(root)
    big_size = os.path.getsize(os.path.join(root, "big.log"))
    CHUNK = 2 * 1024 * 1024
    ref_count, ref_crc, longest = reference(root)
    print(f"big.log is {big_size / 2**20:.1f} MiB; chunks of {CHUNK >> 20} MiB; "
          f"{ref_count} lines in total, longest line {longest} bytes")

    # ---- Part 1 as plain Python ----
    plan = plan_chunks([("a", 10), ("b", 0), ("c", 4)], 4)
    assert plan is not None, "plan_chunks returned None. Return a list of (path, offset, length)."
    assert list(plan) == [("a", 0, 4), ("a", 4, 4), ("a", 8, 2), ("c", 0, 4)], (
        f"plan_chunks([('a', 10), ('b', 0), ('c', 4)], 4) returned {plan}. Expected "
        "[('a', 0, 4), ('a', 4, 4), ('a', 8, 2), ('c', 0, 4)]: every byte covered "
        "once, no chunk for an empty file, a shorter last chunk.")

    # ---- Part 2 as plain Python, for every chunk size ----
    sample = b"aa\nbbbb\n\nc\nddddd"
    expected = [(0, b"aa"), (3, b"bbbb"), (8, b""), (9, b"c"), (11, b"ddddd")]
    for size in range(1, len(sample) + 2):
        got = []
        for _, off, ln in plan_chunks([("s", len(sample))], size):
            lines = read_chunk_lines(io.BytesIO(sample), off, ln)
            assert lines is not None, "read_chunk_lines returned None. Make it a generator (yield)."
            got.extend(lines)
        assert got == expected, (
            f"With chunks of {size} bytes over {sample!r} the lines were {got}, "
            f"expected {expected}. Each line must come out exactly once, from the "
            "chunk that holds its first byte; a line that starts exactly at "
            "offset + length belongs to the next chunk.")
    print("plan_chunks and read_chunk_lines pass as plain Python")

    spark = SparkSession.builder.master("local[4]").getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    spark.dataSource.register(ChunkedLines)

    df = (spark.read.format("chunked_lines")
          .option("path", root).option("chunk_bytes", str(CHUNK))
          .option("audit_dir", audit).load())

    expected_parts = sum(-(-os.path.getsize(os.path.join(root, n)) // CHUNK)
                         for n in os.listdir(root))
    parts = df.rdd.getNumPartitions()
    assert parts == expected_parts, (
        f"The source made {parts} partitions; expected {expected_parts} "
        f"(one per started {CHUNK >> 20} MiB of each non-empty file).")

    stats = df.agg(F.count("*").alias("n"),
                   F.sum(F.crc32(F.encode("line", "UTF-8"))).alias("crc"),
                   F.count_distinct("path", "line_offset").alias("starts")).first()
    print(f"Spark read {stats.n} lines from {parts} partitions; the reference has {ref_count}")
    assert stats.n == ref_count, (
        f"Spark returned {stats.n} lines but the files hold {ref_count}. Lines at "
        "chunk boundaries are lost or duplicated.")
    assert stats.starts == stats.n, (
        "A line was returned twice (a duplicate (path, line_offset)). The chunk "
        "that does not own a line must skip it.")
    assert stats.crc == ref_crc, (
        "The line count is right but the content differs: a line was cut at a "
        "chunk boundary. Keep reading past the end of the chunk to finish a line.")

    tail = (df.filter(F.col("path").endswith("no_trailing_newline.log"))
              .orderBy("line_offset").select("line").collect())
    assert [r.line for r in tail] == ["first", "second", "third-without-newline"], (
        f"no_trailing_newline.log came back as {[r.line for r in tail]}.")

    # ---- Evidence that no task held a whole file ----
    audits = [json.load(open(os.path.join(audit, n))) for n in os.listdir(audit)]
    assert len(audits) == expected_parts, (
        f"Expected one audit record per partition ({expected_parts}), found {len(audits)}.")
    worst = max(a["consumed"] for a in audits)
    print(f"Most bytes any task read: {worst} (chunk {CHUNK}, longest line "
          f"{longest}, big.log {big_size})")
    assert worst <= CHUNK + longest, (
        f"A task read {worst} bytes, more than one chunk plus one line "
        f"({CHUNK + longest}). Stop at the first line that starts at or after "
        "offset + length.")

    # ---- Part 3: an inventory that never opens the files ----
    inv = blob_inventory(spark, root)
    assert inv is not None, "blob_inventory returned None."
    assert sorted(inv.columns) == ["length", "path"], (
        f"blob_inventory should have the columns path and length, not {inv.columns}.")
    read_schema = [l.strip() for l in plan_text(inv).splitlines()
                   if l.strip().startswith("ReadSchema")]
    print(read_schema[0])
    assert "content" not in read_schema[0], (
        "The binaryFile scan still reads content. Select only path and length.")
    total = inv.agg(F.sum("length")).first()[0]
    assert total == sum(os.path.getsize(os.path.join(root, n)) for n in os.listdir(root))

    spark.stop()
    shutil.rmtree(tmp)
    print("All tests passed!")
