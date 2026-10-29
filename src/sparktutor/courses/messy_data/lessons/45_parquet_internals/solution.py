"""
Parquet from the Inside - Solution

Read a Parquet footer byte by byte, decode its Thrift metadata yourself, then
design a file layout for a scaled-up copy of the messy events so that three
queries skip most of the file. The harness measures skipping with the scan's
own `number of output rows` metric, never with timings.
"""

import glob
import os
import struct

from pyspark.sql import SparkSession, functions as sf

MAGIC = b"PAR1"


# ---- Provided: a Thrift compact protocol reader (the same one as in the lesson) ----
class Compact:
    """Decode Thrift compact protocol structs into {field_id: value} dicts."""

    def __init__(self, buf, pos=0):
        self.buf, self.pos = buf, pos

    def byte(self):
        b = self.buf[self.pos]
        self.pos += 1
        return b

    def varint(self):
        shift = result = 0
        while True:
            b = self.byte()
            result |= (b & 0x7F) << shift
            if not b & 0x80:
                return result
            shift += 7

    def zigzag(self):
        n = self.varint()
        return (n >> 1) ^ -(n & 1)

    def value(self, t):
        if t in (1, 2):                      # booleans live in the field header
            return t == 1
        if t == 3:                           # i8
            return struct.unpack("b", bytes([self.byte()]))[0]
        if t in (4, 5, 6):                   # i16, i32, i64 are zigzag varints
            return self.zigzag()
        if t == 7:                           # double, 8 bytes little-endian
            v = struct.unpack_from("<d", self.buf, self.pos)[0]
            self.pos += 8
            return v
        if t == 8:                           # binary: varint length, then bytes
            n = self.varint()
            v = bytes(self.buf[self.pos:self.pos + n])
            self.pos += n
            return v
        if t in (9, 10):                     # list or set
            h = self.byte()
            size, et = h >> 4, h & 0x0F
            if size == 15:
                size = self.varint()
            if et in (1, 2):                 # booleans in a list take one byte each
                return [self.byte() == 1 for _ in range(size)]
            return [self.value(et) for _ in range(size)]
        if t == 11:                          # map
            size = self.varint()
            if size == 0:
                return {}
            kv = self.byte()
            return {self.value(kv >> 4): self.value(kv & 0x0F) for _ in range(size)}
        if t == 12:
            return self.struct()
        raise ValueError(f"unknown compact type {t} at byte {self.pos}")

    def struct(self):
        fields, last = {}, 0
        while True:
            h = self.byte()
            if h == 0:                       # STOP
                return fields
            delta, t = h >> 4, h & 0x0F
            fid = last + delta if delta else self.zigzag()
            fields[fid] = self.value(t)
            last = fid


# ---- Your code ----
def footer_bytes(path):
    """Return the raw Thrift FileMetaData bytes of the Parquet file at `path`.

    A Parquet file is: b"PAR1", the column chunks, the footer, a 4-byte
    little-endian footer length, and b"PAR1" again. Raise ValueError if
    either magic is missing or the length does not fit in the file.
    """
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 12 or data[:4] != MAGIC or data[-4:] != MAGIC:
        raise ValueError(f"{path} is not a Parquet file (missing PAR1 magic)")
    (length,) = struct.unpack("<I", data[-8:-4])
    if length > len(data) - 12:
        raise ValueError(f"{path}: footer length {length} is larger than the file")
    return data[-8 - length:-8]


def row_group_stats(path, column):
    """[(num_rows, min, max), ...] per row group for a top-level INT64 column.

    Decode the footer with Compact. Field ids (parquet.thrift):
    FileMetaData 4 = row_groups; RowGroup 1 = columns, 3 = num_rows;
    ColumnChunk 3 = meta_data; ColumnMetaData 3 = path_in_schema,
    12 = statistics; Statistics 5 = max_value, 6 = min_value (plain-encoded,
    so an INT64 is 8 little-endian bytes).
    """
    meta = Compact(footer_bytes(path)).struct()
    target = column.encode()
    out = []
    for rg in meta[4]:
        for chunk in rg[1]:
            md = chunk[3]
            if md[3] == [target]:
                stats = md[12]
                lo = struct.unpack("<q", stats[6])[0]
                hi = struct.unpack("<q", stats[5])[0]
                out.append((rg[3], lo, hi))
    return out


def write_layout(events, path):
    """Write `events` to `path` so that the harness queries skip most row groups.

    The design:
    - Cluster by day, then sort by user_id inside each day. A ts window
      then touches one day's row groups, and a user lookup touches one or
      two row groups per day.
    - Small row groups (1000 rows) so a lookup reads little.
    - A bloom filter on session_id, sized for one row group (expected NDV),
      because a random id has useless min/max.
    - TIMESTAMP_MICROS instead of the default INT96, which has no statistics.
    """
    (events
        .withColumn("_day", sf.to_date("ts"))
        .repartition(1)
        .sortWithinPartitions("_day", "user_id")
        .drop("_day")
        .write.mode("overwrite")
        .option("parquet.block.row.count.limit", 1000)
        .option("parquet.bloom.filter.enabled#session_id", "true")
        .option("parquet.bloom.filter.expected.ndv#session_id", 1000)
        .option("spark.sql.parquet.outputTimestampType", "TIMESTAMP_MICROS")
        .parquet(path))


# ---- Test harness ----
def make_events(spark, n=200_000):
    """A scaled-up copy of the day-one events: same columns plus a session id.

    Rows arrive in random order across 10 days and 5000 users, like a real
    ingestion log. Built from hashes, so it is the same on every run.
    """
    h = lambda salt: sf.pmod(sf.hash("id", sf.lit(salt)), sf.lit(1 << 30))  # noqa: E731
    return spark.range(n).select(
        (h(1) % 5000).cast("bigint").alias("user_id"),
        sf.substring(sf.sha2(sf.col("id").cast("string"), 256), 1, 16).alias("session_id"),
        sf.element_at(sf.array(*[sf.lit(e) for e in ["view", "cart", "purchase"]]),
                      (h(2) % 3 + 1).cast("int")).alias("event"),
        ((h(3) % 5000) / 100).cast("decimal(9,2)").alias("amount"),
        sf.timestamp_seconds(sf.lit(1790812800) + (h(4) % 10) * 86400 + h(5) % 86400).alias("ts"),
    )


def rows_scanned(df):
    """Run `df` and return (rows, total `number of output rows` of its Parquet scans).

    The vectorized reader returns every row of every row group (and page)
    that survived skipping, so this metric counts what was actually read.
    Uses the JVM plan, so it needs classic mode.
    """
    rows = df.collect()
    plan = df._jdf.queryExecution().executedPlan()
    total = 0

    def walk(node):
        nonlocal total
        name = node.getClass().getSimpleName()
        if name == "AdaptiveSparkPlanExec":
            return walk(node.executedPlan())
        if name == "FileSourceScanExec":
            total += node.metrics().apply("numOutputRows").value()
        children = node.children().iterator()
        while children.hasNext():
            walk(children.next())

    walk(plan)
    return rows, total


if __name__ == "__main__":
    import tempfile

    import pyarrow.parquet as pq

    spark = (SparkSession.builder
        .appName("ParquetInternals")
        .master("local[4]")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    out = tempfile.mkdtemp(prefix="pq_internals_")
    try:
        N = 200_000
        events = make_events(spark, N).cache()
        assert events.count() == N

        # The naive layout: one file, one row group, arrival order, default settings
        naive = os.path.join(out, "naive")
        events.coalesce(1).write.parquet(naive)
        naive_file = glob.glob(os.path.join(naive, "*.parquet"))[0]
        naive_size = os.path.getsize(naive_file)

        # 1. footer_bytes
        fb = footer_bytes(naive_file)
        assert isinstance(fb, (bytes, bytearray)), f"footer_bytes should return bytes, got {type(fb)}"
        expected_len = pq.ParquetFile(naive_file).metadata.serialized_size
        assert len(fb) == expected_len, (
            f"The footer is {expected_len} bytes (pyarrow's serialized_size), you returned {len(fb)}. "
            "Read the 4-byte little-endian length just before the final PAR1")
        meta = Compact(fb).struct()
        assert meta.get(3) == N, f"Decoding your footer gave num_rows={meta.get(3)}, expected {N}"
        for bad in ["data/messy/images/scans/corrupt.png", "data/messy/docs/returns.md"]:
            try:
                footer_bytes(bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f"footer_bytes({bad!r}) should raise ValueError: it is not Parquet")
        truncated = os.path.join(out, "truncated.parquet")
        with open(naive_file, "rb") as src, open(truncated, "wb") as dst:
            dst.write(src.read()[:-1])
        try:
            footer_bytes(truncated)
        except ValueError:
            pass
        else:
            raise AssertionError("footer_bytes should raise ValueError when the trailing PAR1 is cut off")

        # 2. The layout
        layout = os.path.join(out, "layout")
        write_layout(events, layout)
        files = sorted(glob.glob(os.path.join(layout, "**", "*.parquet"), recursive=True))
        assert files, f"write_layout wrote no .parquet files under {layout}"
        assert len(files) <= 16, f"Keep it to at most 16 files, you wrote {len(files)}"
        layout_df = spark.read.parquet(layout)
        assert layout_df.count() == N, f"The layout must keep every row: expected {N}, got {layout_df.count()}"
        total_rgs, total_size = 0, 0
        for f in files:
            md = pq.ParquetFile(f).metadata
            total_rgs += md.num_row_groups
            total_size += os.path.getsize(f)
            names = [md.schema.column(i).name for i in range(md.num_columns)]
            assert "session_id" in names and "ts" in names, f"{f} lost a column: {names}"
            ts_col = md.schema.column(names.index("ts"))
            assert ts_col.physical_type == "INT64" and "micro" in str(ts_col.logical_type).lower(), (
                f"ts is stored as {ts_col.physical_type} {ts_col.logical_type}. The default INT96 has "
                "no min/max statistics, so a ts filter can't skip anything: write TIMESTAMP_MICROS")
            for i in range(md.num_row_groups):
                assert md.row_group(i).column(names.index("session_id")).bloom_filter_offset is not None, (
                    f"Row group {i} of {os.path.basename(f)} has no bloom filter on session_id")
        assert total_rgs <= 400, (
            f"{total_rgs} row groups is too many for {N} rows: every row group costs footer space "
            "and a seek. Stay at or under 400")
        assert total_size <= 1.5 * naive_size, (
            f"The layout is {total_size:,} bytes, more than 1.5x the naive file ({naive_size:,}). "
            "A bloom filter without parquet.bloom.filter.expected.ndv is 1 MiB per row group")

        # 3. row_group_stats against pyarrow
        for f in files[:3]:
            got = row_group_stats(f, "user_id")
            md = pq.ParquetFile(f).metadata
            j = [md.schema.column(i).name for i in range(md.num_columns)].index("user_id")
            want = [(md.row_group(i).num_rows, md.row_group(i).column(j).statistics.min,
                     md.row_group(i).column(j).statistics.max) for i in range(md.num_row_groups)]
            assert got == want, (
                f"row_group_stats({os.path.basename(f)!r}, 'user_id') disagrees with pyarrow. "
                f"First entries: yours {got[:3]}, pyarrow {want[:3]}")

        # 4. The queries: same answers as the naive file, far fewer rows read
        key = events.filter("user_id = 4321").select("session_id").first()[0]
        queries = {
            "user_id = 1234": (sf.col("user_id") == 1234, 0.15),
            "session_id = key": (sf.col("session_id") == key, 0.05),
            "two hours of 2026-10-05": ((sf.col("ts") >= sf.lit("2026-10-05 08:00:00").cast("timestamp"))
                                       & (sf.col("ts") < sf.lit("2026-10-05 10:00:00").cast("timestamp")), 0.15),
        }
        cols = ["user_id", "session_id", "event", "amount", "ts"]
        print(f"{'query':28} {'rows':>5} {'naive scan':>11} {'layout scan':>12}")
        for name, (cond, limit) in queries.items():
            expected = sorted(tuple(r) for r in events.filter(cond).select(cols).collect())
            naive_rows, naive_scan = rows_scanned(spark.read.parquet(naive).filter(cond).select(cols))
            got_rows, scanned = rows_scanned(spark.read.parquet(layout).filter(cond).select(cols))
            assert sorted(tuple(r) for r in got_rows) == expected, (
                f"Query {name!r} returned different rows on your layout: {len(got_rows)} vs {len(expected)}")
            print(f"{name:28} {len(expected):5} {naive_scan:11,} {scanned:12,}")
            assert scanned <= limit * N, (
                f"Query {name!r} still reads {scanned:,} of {N:,} rows ({scanned / N:.0%}); "
                f"the target is at most {limit:.0%}. Check sort order, row group size, the bloom "
                "filter and the timestamp type")

        print(f"\nnaive: 1 file, {naive_size:,} bytes; layout: {len(files)} file(s), "
              f"{total_rgs} row groups, {total_size:,} bytes")
        print("All tests passed!")
    finally:
        spark.stop()
