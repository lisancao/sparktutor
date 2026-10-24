"""
Python Data Sources - Starter Code

Complete the sensor data source and `use_sensor_source(spark, workdir)`:
1. SensorBatchReader.partitions(): split `rows` into `num_partitions`
   RangePartition ranges; read() yields reading(i) for its range
2. SensorBatchReader.pushFilters(): keep EqualTo on ("sensor",) for
   yourself, yield every other filter back to Spark; read() applies it
3. SensorStreamReader: default read limit ReadMaxRows(max_rows),
   prepareForTriggerAvailableNow() freezes the target offset, and
   latestOffset(start, limit) honors ReadAllAvailable and ReadMaxRows
4. use_sensor_source(): enable spark.sql.python.filterPushdown.enabled,
   register the source, run a batch read, a filtered read, and an
   availableNow stream into a memory sink named "sensor_stream"
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
        # TODO: for each filter, if it is EqualTo on ("sensor",) save f.value
        #       in self.sensor_filter, otherwise `yield f`
        for f in filters:
            yield f

    def partitions(self):
        # TODO: return num_partitions RangePartition objects covering 0..rows
        return [RangePartition(0, self.rows)]

    def read(self, partition):
        # TODO: yield reading(i) for i in the partition's range, skipping rows
        #       whose sensor does not match self.sensor_filter (when set)
        return iter([])


class SensorStreamReader(DataSourceStreamReader, SupportsTriggerAvailableNow):
    def __init__(self, options):
        self.total = int(options.get("total", 25))
        self.max_rows = int(options.get("maxRowsPerBatch", 10))
        self.target = None

    def initialOffset(self):
        return {"seq": 0}

    def getDefaultReadLimit(self):
        # TODO: return ReadMaxRows(self.max_rows)
        return ReadAllAvailable()

    def prepareForTriggerAvailableNow(self):
        # TODO: freeze the target offset at self.total
        pass

    def latestOffset(self, start, limit):
        # TODO: end = target (or total); return {"seq": end} for ReadAllAvailable,
        #       else {"seq": min(end, start["seq"] + limit.max_rows)}
        return start

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

    # TODO: enable spark.sql.python.filterPushdown.enabled BEFORE the first read,
    #       then spark.dataSource.register(SensorDataSource)

    # TODO: batch read with option("rows", 30); count distinct spark_partition_id()
    batch = None  # Replace
    num_partitions = None  # Replace

    # TODO: same read, filtered on (sensor == "s2") & (value > 21)
    s2 = None  # Replace
    s2_plan = s2._jdf.queryExecution().executedPlan().toString() if s2 is not None else ""
    s2_rows = None  # Replace

    # TODO: readStream.format("sensors").option("total", 25).option("maxRowsPerBatch", 10)
    #       -> writeStream memory sink "sensor_stream", checkpoint under workdir,
    #       trigger(availableNow=True); start and awaitTermination()
    query = None  # Replace
    batch_sizes = [p["numInputRows"] for p in query.recentProgress if p["numInputRows"] > 0] if query else []
    streamed = None  # Replace with spark.table("sensor_stream").count()

    return {
        "batch": batch,
        "num_partitions": num_partitions,
        "s2_rows": s2_rows,
        "s2_plan": s2_plan,
        "batch_sizes": batch_sizes,
        "streamed": streamed,
    }


# ---- Test harness (do not modify below this line) ----
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
