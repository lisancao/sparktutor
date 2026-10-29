"""
Your First Python Data Source - Solution

A "counter" data source: spark.read.format("counter").option("rows", 10).load()
returns rows (id, label) for id = 0 .. rows-1, split into parallel partitions.

Options (all arrive as strings, keys are case-insensitive):
  rows        required, a whole number >= 0
  partitions  optional, default 2, a whole number >= 1
  prefix      optional, default "row"; label is f"{prefix}-{id}"

Pieces:
1. plan_ranges: split rows into contiguous (start, end) ranges (plain Python)
2. RangePartition: one task's share of the work
3. CounterDataSource: name, schema and reader
4. CounterReader: validates options, plans partitions, reads rows
5. read_without_spark: runs the reader as plain Python, for unit tests
"""

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.datasource import CaseInsensitiveDict, DataSource, DataSourceReader, InputPartition
from pyspark.sql.types import LongType, StringType, StructField, StructType

SCHEMA = "id long, label string"

# The same schema as objects: building it needs no Spark session, so plain
# Python tests can use it
SCHEMA_STRUCT = StructType([StructField("id", LongType()), StructField("label", StringType())])


def plan_ranges(rows, partitions):
    """Split range(rows) into at most `partitions` contiguous (start, end) pairs.

    Sizes differ by at most one, earlier ranges get the extra rows, and no
    range is empty: plan_ranges(10, 3) == [(0, 4), (4, 7), (7, 10)].
    """
    n = min(partitions, rows)
    if n <= 0:
        return []
    base, extra = divmod(rows, n)
    ranges, start = [], 0
    for i in range(n):
        end = start + base + (1 if i < extra else 0)
        ranges.append((start, end))
        start = end
    return ranges


class RangePartition(InputPartition):
    """The ids one task reads: start (inclusive) to end (exclusive)."""

    def __init__(self, start, end):
        self.start = start
        self.end = end


def _whole_number(options, key, default, minimum):
    raw = options.get(key, default)
    if raw is None:
        raise ValueError(f"option '{key}' is required")
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"option '{key}' must be a whole number, got {raw!r}") from None
    if value < minimum:
        raise ValueError(f"option '{key}' must be >= {minimum}, got {value}")
    return value


class CounterDataSource(DataSource):
    """format("counter"): rows (id, label) for id in 0 .. rows-1."""

    @classmethod
    def name(cls):
        return "counter"

    def schema(self):
        return SCHEMA

    def reader(self, schema):
        return CounterReader(self.options, schema)


class CounterReader(DataSourceReader):
    def __init__(self, options, schema):
        # Runs when Spark plans the query: fail early with a clear message
        self.rows = _whole_number(options, "rows", None, 0)
        self.partition_count = _whole_number(options, "partitions", "2", 1)
        self.prefix = options.get("prefix", "row")
        # The schema may be the user's (.schema(...)): produce only its
        # columns, in its order
        self.columns = [field.name for field in schema.fields]
        unknown = [c for c in self.columns if c not in ("id", "label")]
        if unknown:
            raise ValueError(f"counter has no column(s) {unknown}; available: id, label")

    def partitions(self):
        return [RangePartition(start, end) for start, end in plan_ranges(self.rows, self.partition_count)]

    def read(self, partition):
        # With no partitions planned, Spark still calls read() once with
        # InputPartition(None): produce nothing in that case
        if not isinstance(partition, RangePartition):
            return
        for i in range(partition.start, partition.end):
            values = {"id": i, "label": f"{self.prefix}-{i}"}
            yield tuple(values[c] for c in self.columns)


def read_without_spark(options):
    """Run the reader the way Spark would, as plain Python. Returns all rows."""
    reader = CounterReader(CaseInsensitiveDict(options), SCHEMA_STRUCT)
    return [row for partition in reader.partitions() for row in reader.read(partition)]


# ---- Test harness ----
if __name__ == "__main__":
    import pickle

    # 1. Plain Python first: no Spark session exists yet
    got = plan_ranges(10, 3)
    assert got == [(0, 4), (4, 7), (7, 10)], f"plan_ranges(10, 3) should be [(0, 4), (4, 7), (7, 10)], got {got}"
    got = plan_ranges(2, 5)
    assert got == [(0, 1), (1, 2)], f"plan_ranges(2, 5) should not make empty ranges: expected [(0, 1), (1, 2)], got {got}"
    assert plan_ranges(0, 2) == [], f"plan_ranges(0, 2) should be [], got {plan_ranges(0, 2)}"

    rows = read_without_spark({"rows": "5", "partitions": "2"})
    assert rows == [(0, "row-0"), (1, "row-1"), (2, "row-2"), (3, "row-3"), (4, "row-4")], (
        f"read_without_spark({{'rows': '5', 'partitions': '2'}}) returned {rows}")
    assert read_without_spark({"ROWS": "2", "Prefix": "n"}) == [(0, "n-0"), (1, "n-1")], (
        "Option keys are case-insensitive: read them from the CaseInsensitiveDict Spark passes in")
    for bad, words in [({}, "required"), ({"rows": "ten"}, "whole number"), ({"rows": "3", "partitions": "0"}, ">= 1")]:
        try:
            read_without_spark(bad)
        except ValueError as e:
            assert words in str(e), f"For options {bad} the ValueError should mention {words!r}, got: {e}"
        else:
            raise AssertionError(f"CounterReader should raise ValueError for options {bad}")
    reader = CounterReader(CaseInsensitiveDict({"rows": "3"}), SCHEMA_STRUCT)
    pickle.loads(pickle.dumps(reader))  # Spark ships readers to executors by pickling them
    print("Plain Python tests passed (no Spark session needed)")

    # 2. Through Spark
    spark = (SparkSession.builder
             .appName("FirstPythonDataSource")
             .master("local[*]")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    try:
        assert CounterDataSource.name() == "counter", f"name() should return 'counter', got {CounterDataSource.name()!r}"
        spark.dataSource.register(CounterDataSource)

        df = spark.read.format("counter").option("rows", 10).option("partitions", 3).load()
        assert df.dtypes == [("id", "bigint"), ("label", "string")], f"Schema should be id bigint, label string; got {df.dtypes}"
        got = [tuple(r) for r in df.orderBy("id").collect()]
        assert got == [(i, f"row-{i}") for i in range(10)], f"Expected ids 0..9 labelled row-<id>, got {got}"
        sizes = sorted((r["n"] for r in df.groupBy(F.spark_partition_id().alias("p"))
                        .agg(F.count("*").alias("n")).collect()), reverse=True)
        assert sizes == [4, 3, 3], f"10 rows in 3 partitions should be split 4, 3, 3; got {sizes}"

        assert spark.read.format("COUNTER").option("ROWS", 4).load().count() == 4, (
            "Format names and option keys are case-insensitive")
        labels = [r["label"] for r in spark.read.format("counter").option("rows", 2).option("prefix", "item")
                  .load().orderBy("id").collect()]
        assert labels == ["item-0", "item-1"], f"prefix 'item' should give labels item-0, item-1; got {labels}"

        only_ids = spark.read.format("counter").schema("id long").option("rows", 3).load()
        assert only_ids.columns == ["id"] and only_ids.count() == 3, (
            "With .schema('id long') the reader must produce only the id column")
        swapped = spark.read.format("counter").schema("label string, id long").option("rows", 1).load().first()
        assert tuple(swapped) == ("row-0", 0), f"Produce columns in the order of the schema Spark passes in, got {tuple(swapped)}"

        assert spark.read.format("counter").option("rows", 0).load().count() == 0, (
            "rows 0 plans no partitions; Spark then calls read() once with InputPartition(None), which must yield nothing")

        try:
            spark.read.format("counter").load().collect()
        except Exception as e:  # noqa: BLE001
            text = str(e)
            assert "PYTHON_DATA_SOURCE_ERROR" in text and "option 'rows' is required" in text, (
                f"A missing rows option should fail with PYTHON_DATA_SOURCE_ERROR and your message; got {text[:300]}")
        else:
            raise AssertionError("Reading without the rows option should fail")

        spark.sql("CREATE OR REPLACE TEMPORARY VIEW five USING counter OPTIONS (rows '5')")
        total = spark.sql("SELECT sum(id) AS s FROM five").first()["s"]
        assert total == 10, f"SELECT sum(id) over 5 rows should be 10, got {total}"

        print("Rows per partition:")
        (df.groupBy(F.spark_partition_id().alias("partition"))
           .agg(F.min("id").alias("first_id"), F.max("id").alias("last_id"), F.count("*").alias("rows"))
           .orderBy("partition").show())
        df.orderBy("id").show()
        print("All tests passed!")
    finally:
        spark.stop()
