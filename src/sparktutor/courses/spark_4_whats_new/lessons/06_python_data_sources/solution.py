"""
Python Data Sources - Solution

A pure-Python data source with partitioned batch reads, filter pushdown,
and a rate-limited streaming reader that supports Trigger.AvailableNow.
"""

import tempfile

from pyspark.sql import SparkSession, functions as sf
from pyspark.sql.datasource import (
    DataSource, DataSourceReader, DataSourceStreamReader, InputPartition, EqualTo,
)
from pyspark.sql.streaming.datasource import (
    ReadAllAvailable, ReadMaxRows, SupportsTriggerAvailableNow,
)


SENSORS = ["s1", "s2", "s3"]


def reading(i):
    """Deterministic fake reading number i: (seq, sensor, value)."""
    return (i, SENSORS[i % len(SENSORS)], round(20.0 + (i * 7 % 13) * 0.5, 1))


class RangePartition(InputPartition):
    def __init__(self, start, end):
        self.start, self.end = start, end


class SensorDataSource(DataSource):
    """format("sensors"): option `rows` for batch, `total` and `maxRowsPerBatch` for streaming."""

    @classmethod
    def name(cls):
        return "sensors"

    def schema(self):
        return "seq int, sensor string, value double"

    def reader(self, schema):
        return SensorBatchReader(self.options)

    def streamReader(self, schema):
        return SensorStreamReader(self.options)


class SensorBatchReader(DataSourceReader):
    def __init__(self, options):
        self.rows = int(options.get("rows", 30))
        self.num_partitions = int(options.get("partitions", 3))
        self.sensor_filter = None

    def pushFilters(self, filters):
        # Handle `sensor = '...'` ourselves; hand every other filter back to Spark.
        for f in filters:
            if isinstance(f, EqualTo) and f.attribute == ("sensor",):
                self.sensor_filter = f.value
            else:
                yield f

    def partitions(self):
        step = -(-self.rows // self.num_partitions)
        return [RangePartition(s, min(s + step, self.rows)) for s in range(0, self.rows, step)]

    def read(self, partition):
        for i in range(partition.start, partition.end):
            row = reading(i)
            if self.sensor_filter is None or row[1] == self.sensor_filter:
                yield row


class SensorStreamReader(DataSourceStreamReader, SupportsTriggerAvailableNow):
    def __init__(self, options):
        self.total = int(options.get("total", 25))
        self.max_rows = int(options.get("maxRowsPerBatch", 10))
        self.target = None

    def initialOffset(self):
        return {"seq": 0}

    def getDefaultReadLimit(self):
        # Admission control (4.2): cap each micro-batch at max_rows.
        return ReadMaxRows(self.max_rows)

    def prepareForTriggerAvailableNow(self):
        # Freeze the end of the data at query start.
        self.target = self.total

    def latestOffset(self, start, limit):
        end = self.target if self.target is not None else self.total
        if isinstance(limit, ReadAllAvailable):
            return {"seq": end}
        return {"seq": min(end, start["seq"] + limit.max_rows)}

    def reportLatestOffset(self):
        return {"seq": self.total}

    def partitions(self, start, end):
        return [RangePartition(start["seq"], end["seq"])]

    def read(self, partition):
        for i in range(partition.start, partition.end):
            yield reading(i)

    def commit(self, end):
        pass


def use_sensor_source(spark, workdir):
    """Register the source, read it in batch and in streaming."""

    # Filter pushdown (4.1) is behind an internal flag, and a reader that
    # implements pushFilters() fails with DATA_SOURCE_PUSHDOWN_DISABLED when
    # the flag is off. Turn it on before the first read.
    spark.conf.set("spark.sql.python.filterPushdown.enabled", "true")
    spark.dataSource.register(SensorDataSource)

    # 1. Batch read: three partitions, one Python task each.
    batch = spark.read.format("sensors").option("rows", 30).load()
    num_partitions = batch.select(sf.spark_partition_id().alias("p")).distinct().count()

    # 2. With pushdown on, sensor = 's2' is evaluated inside read(), and only
    #    value > 21 stays in Spark's Filter.
    s2 = (spark.read.format("sensors").option("rows", 30).load()
          .filter((sf.col("sensor") == "s2") & (sf.col("value") > 21)))
    s2_plan = s2._jdf.queryExecution().executedPlan().toString()
    s2_rows = s2.count()

    # 3. Streaming with admission control and Trigger.AvailableNow (4.2).
    query = (spark.readStream.format("sensors")
             .option("total", 25).option("maxRowsPerBatch", 10).load()
             .writeStream.format("memory").queryName("sensor_stream")
             .option("checkpointLocation", f"{workdir}/checkpoint")
             .trigger(availableNow=True)
             .start())
    query.awaitTermination()
    batch_sizes = [p["numInputRows"] for p in query.recentProgress if p["numInputRows"] > 0]
    streamed = spark.table("sensor_stream").count()

    return {
        "batch": batch,
        "num_partitions": num_partitions,
        "s2_rows": s2_rows,
        "s2_plan": s2_plan,
        "batch_sizes": batch_sizes,
        "streamed": streamed,
    }


# ---- Test harness ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("PythonDataSourceTest")
        .master("local[*]")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate())

    workdir = tempfile.mkdtemp(prefix="sparktutor_pyds_")
    result = use_sensor_source(spark, workdir)
    assert result is not None, "Function returned None"
    assert result["batch"].count() == 30, "Batch read should return 30 rows"
    assert result["num_partitions"] == 3, f"Expected 3 partitions, got {result['num_partitions']}"
    expected_s2 = len([r for r in map(reading, range(30)) if r[1] == "s2" and r[2] > 21])
    assert result["s2_rows"] == expected_s2, f"Expected {expected_s2} s2 rows, got {result['s2_rows']}"
    filter_lines = [l for l in result["s2_plan"].splitlines() if "Filter" in l]
    assert filter_lines and all("s2" not in l for l in filter_lines), \
        f"sensor = 's2' should be pushed into the source, not kept in Spark's Filter: {filter_lines}"
    assert result["batch_sizes"] == [10, 10, 5], f"Admission control should give [10, 10, 5], got {result['batch_sizes']}"
    assert result["streamed"] == 25, f"Expected 25 streamed rows, got {result['streamed']}"
    print("Batch partitions:", result["num_partitions"])
    print("Pushed-down plan:\n", result["s2_plan"])
    print("Micro-batch sizes:", result["batch_sizes"])
    result["batch"].groupBy("sensor").agg(sf.avg("value").alias("avg_value")).orderBy("sensor").show()
    print("All tests passed!")
    spark.stop()
