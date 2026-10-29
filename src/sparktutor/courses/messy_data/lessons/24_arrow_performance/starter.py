"""
Types, Arrow and Performance - Exercise

One sensor source, three ways to hand rows to Spark: Python tuples, Arrow
record batches you build yourself, and Arrow batches from a "vendor" library
whose types do not match the declared schema until you conform them.
"""

import datetime

import pyarrow as pa
from pyspark.sql import SparkSession, functions as sf
from pyspark.sql.datasource import DataSource, DataSourceReader, InputPartition

SCHEMA = "id int, sensor string, value double, ts timestamp"

# The Arrow schema Spark expects for SCHEMA: exact types, same order, nullable.
# TODO: pa.schema([(name, arrow type), ...]) for id, sensor, value and ts
ARROW_SCHEMA = None

BASE = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)


def reading(i):
    """Sensor reading number i as a tuple matching SCHEMA (already written)."""
    return (i, f"s{i % 10}", i * 0.5, BASE + datetime.timedelta(seconds=i))


def vendor_batches(lo, hi, size):
    """Stand-in for a library that returns Arrow data with its own idea of types
    (already written): int64 ids, naive timestamps, columns in another order."""
    for start in range(lo, hi, size):
        ids = list(range(start, min(start + size, hi)))
        yield pa.RecordBatch.from_pydict({
            "value": [i * 0.5 for i in ids],
            "ts": [datetime.datetime(2026, 10, 1) + datetime.timedelta(seconds=i) for i in ids],
            "id": ids,
            "sensor": [f"s{i % 10}" for i in ids],
        })


def read_tuples(lo, hi):
    """Yield one tuple per reading in [lo, hi)."""
    # TODO: yield reading(i) for every i in range(lo, hi)
    return iter([])


def read_arrow(lo, hi, size):
    """Yield the readings in [lo, hi) as RecordBatches of at most `size` rows, typed as ARROW_SCHEMA."""
    # TODO: for each start in range(lo, hi, size), build four pyarrow arrays
    #   (ids as int32, sensor names, values as float64, timestamps as
    #   timestamp('us', tz='UTC')) with the same values as reading(i), and
    #   yield pa.RecordBatch.from_arrays([...], schema=ARROW_SCHEMA)
    return iter([])


def conform(batch):
    """Reorder and cast a RecordBatch to ARROW_SCHEMA (a safe cast: overflow raises)."""
    # TODO: select the columns in ARROW_SCHEMA's order (batch.select(names)),
    #   then cast to ARROW_SCHEMA (batch.cast(schema))
    return None


class SensorSource(DataSource):
    """format("sensors"): options rows, partitions, mode (tuples, arrow, vendor, vendor_raw), batch_size."""

    @classmethod
    def name(cls):
        return "sensors"

    def schema(self):
        return SCHEMA

    def reader(self, schema):
        return SensorReader(self.options)


class SensorReader(DataSourceReader):
    def __init__(self, options):
        self.rows = int(options.get("rows", 100_000))
        self.parts = int(options.get("partitions", 4))
        self.mode = options.get("mode", "tuples")
        self.batch_size = int(options.get("batch_size", 10_000))

    def partitions(self):
        return [InputPartition(i) for i in range(self.parts)]

    def read(self, partition):
        lo = partition.value * self.rows // self.parts
        hi = (partition.value + 1) * self.rows // self.parts
        if self.mode == "tuples":
            return read_tuples(lo, hi)
        if self.mode == "arrow":
            return read_arrow(lo, hi, self.batch_size)
        if self.mode == "vendor":
            return (conform(b) for b in vendor_batches(lo, hi, self.batch_size))
        if self.mode == "vendor_raw":
            return vendor_batches(lo, hi, self.batch_size)
        raise ValueError(f"unknown mode {self.mode!r}")


# ---- Test harness ----
if __name__ == "__main__":
    import time

    # 1. Unit tests without Spark: the readers are plain Python generators
    assert isinstance(ARROW_SCHEMA, pa.Schema), "ARROW_SCHEMA should be a pyarrow.Schema (pa.schema([...]))"
    expected_schema = pa.schema([("id", pa.int32()), ("sensor", pa.string()), ("value", pa.float64()),
                                 ("ts", pa.timestamp("us", tz="UTC"))])
    assert ARROW_SCHEMA.equals(expected_schema), (
        f"ARROW_SCHEMA should be\n{expected_schema}\ngot\n{ARROW_SCHEMA}\n"
        "int is int32, double is float64, timestamp is timestamp('us', tz='UTC')")
    tuples = list(read_tuples(0, 25))
    assert tuples == [reading(i) for i in range(25)], f"read_tuples(0, 25) should yield reading(0) to reading(24)"
    batches = list(read_arrow(0, 25, 10))
    assert [b.num_rows for b in batches] == [10, 10, 5], (
        f"read_arrow(0, 25, 10) should yield batches of 10, 10 and 5 rows, got {[b.num_rows for b in batches]}")
    assert all(b.schema.equals(ARROW_SCHEMA) for b in batches), (
        f"Every batch must have exactly ARROW_SCHEMA, got {batches[0].schema}")
    as_rows = [tuple(r.values()) for b in batches for r in b.to_pylist()]
    assert as_rows == tuples, "read_arrow should hold the same values as read_tuples"
    fixed = conform(next(vendor_batches(0, 5, 5)))
    assert fixed is not None and fixed.schema.equals(ARROW_SCHEMA), (
        f"conform should return a batch with ARROW_SCHEMA, got {None if fixed is None else fixed.schema}")
    assert [tuple(r.values()) for r in fixed.to_pylist()] == [reading(i) for i in range(5)], (
        "conform changed the values: select the columns by name, then cast")

    spark = (SparkSession.builder
        .appName("ArrowPerformance")
        .master("local[*]")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    try:
        spark.dataSource.register(SensorSource)
        n = 400_000

        def summary(mode):
            df = spark.read.format("sensors").option("rows", n).option("mode", mode).load()
            r = df.agg(sf.count("*").alias("rows"), sf.sum("id").alias("ids"), sf.sum("value").alias("values"),
                       sf.count_distinct("sensor").alias("sensors"),
                       sf.min("ts").cast("string").alias("first"), sf.max("ts").cast("string").alias("last")).first()
            return r.asDict()

        expected = {"rows": n, "ids": n * (n - 1) // 2, "values": n * (n - 1) / 4, "sensors": 10,
                    "first": "2026-10-01 00:00:00",
                    "last": str((BASE + datetime.timedelta(seconds=n - 1)).replace(tzinfo=None))}

        # 2. Every mode returns the same data
        timings = {}
        for mode in ["tuples", "arrow", "vendor"]:
            summary(mode)  # warm up the Python workers
            start = time.time()
            got = summary(mode)
            timings[mode] = time.time() - start
            assert got == expected, f"mode={mode}: expected {expected}, got {got}"

        parts = (spark.read.format("sensors").option("rows", 100).option("mode", "arrow").load()
            .select(sf.spark_partition_id()).distinct().count())
        assert parts == 4, f"Expected 4 partitions, got {parts}"

        # 3. Unconformed vendor batches are rejected by the 4.2 type check
        try:
            spark.read.format("sensors").option("rows", 100).option("mode", "vendor_raw").load().collect()
            raise AssertionError("vendor_raw batches should fail with DATA_SOURCE_RETURN_SCHEMA_MISMATCH")
        except AssertionError:
            raise
        except Exception as e:
            assert "DATA_SOURCE_RETURN_SCHEMA_MISMATCH" in str(e), f"Unexpected error: {str(e)[:300]}"

        print(f"{n} rows over 4 partitions (one run each, indicative only):")
        for mode, seconds in timings.items():
            print(f"  {mode:7} {seconds:.2f} s")
        spark.read.format("sensors").option("rows", 20).option("mode", "arrow").load().show(5)
        print("All tests passed!")
    finally:
        spark.stop()
