"""
Structured Streaming - Solution

Batch-tested streaming logic (word count, tumbling windows) plus two real
streaming queries over JSON files: a watermarked windowed aggregation and
a transformWithState processor, both with trigger(availableNow=True).
"""

from datetime import datetime, timedelta

from pyspark.sql import Row, SparkSession, functions as f
from pyspark.sql.streaming import StatefulProcessor, StatefulProcessorHandle
from pyspark.sql.types import StructType, StructField, StringType, TimestampType


TEXT_DATA = [
    ("hello world hello spark",),
    ("spark streaming is great",),
    ("hello streaming world",),
    ("spark spark spark",),
    ("world of streaming data",),
    ("hello data world",),
]

SCHEMA = StructType([
    StructField("line", StringType(), False),
])

# Schema of the JSON sensor readings the harness writes to input_dir.
READING_SCHEMA = "sensor STRING, temp INT, event_time TIMESTAMP"

ROCKSDB_PROVIDER = "org.apache.spark.sql.execution.streaming.state.RocksDBStateStoreProvider"


def streaming_word_count(spark):
    """Simulate a streaming word count in batch mode."""

    lines_df = spark.createDataFrame(TEXT_DATA, SCHEMA)

    words_df = lines_df.select(
        f.explode(f.split("line", " ")).alias("word")
    )

    counts_df = words_df.groupBy("word").count()

    result = counts_df.orderBy(f.col("count").desc())

    return result


def streaming_windowed_count(spark):
    """Demonstrate windowed aggregation concepts in batch mode.

    Creates timestamped word data, applies a time-based window,
    and counts words per window.
    """
    base_time = datetime(2024, 1, 1, 12, 0, 0)
    timestamped_data = [
        ("hello spark", base_time),
        ("hello world", base_time + timedelta(minutes=2)),
        ("spark streaming", base_time + timedelta(minutes=5)),
        ("hello spark", base_time + timedelta(minutes=8)),
        ("streaming world", base_time + timedelta(minutes=12)),
        ("spark data", base_time + timedelta(minutes=15)),
    ]

    ts_schema = StructType([
        StructField("line", StringType(), False),
        StructField("event_time", TimestampType(), False),
    ])

    ts_df = spark.createDataFrame(timestamped_data, ts_schema)

    words_df = ts_df.select(
        f.explode(f.split("line", " ")).alias("word"),
        "event_time",
    )

    windowed_counts = (words_df
        .groupBy(f.window("event_time", "10 minutes"), "word")
        .count()
        .orderBy("window", f.col("count").desc()))

    return windowed_counts


def sensor_window_stream(spark, input_dir, checkpoint_dir):
    """Max temperature per sensor per 10-minute window, as a real stream."""

    readings = spark.readStream.schema(READING_SCHEMA).json(input_dir)

    windowed = (readings
        .withWatermark("event_time", "10 minutes")
        .groupBy(f.window("event_time", "10 minutes"), "sensor")
        .agg(f.max("temp").alias("max_temp")))

    query = (windowed.writeStream
        .format("memory")
        .queryName("sensor_windows")
        .outputMode("complete")
        .option("checkpointLocation", checkpoint_dir)
        .trigger(availableNow=True)
        .start())
    query.awaitTermination()

    return spark.table("sensor_windows")


class ViolationCounter(StatefulProcessor):
    """Keeps a running count of readings above 100 degrees per sensor."""

    def init(self, handle: StatefulProcessorHandle) -> None:
        self.violations = handle.getValueState("violations", "count INT")

    def handleInputRows(self, key, rows, timerValues):
        count = self.violations.get()[0] if self.violations.exists() else 0
        for row in rows:
            if row.temp is not None and row.temp > 100:
                count += 1
        self.violations.update((count,))
        yield Row(sensor=key[0], violations=count)

    def close(self) -> None:
        pass


def sensor_violations(spark, input_dir, checkpoint_dir):
    """Count over-temperature readings per sensor with transformWithState."""

    spark.conf.set("spark.sql.streaming.stateStore.providerClass", ROCKSDB_PROVIDER)

    readings = spark.readStream.schema(READING_SCHEMA).json(input_dir)

    alerts = readings.groupBy("sensor").transformWithState(
        statefulProcessor=ViolationCounter(),
        outputStructType="sensor STRING, violations INT",
        outputMode="Update",
        timeMode="None",
    )

    query = (alerts.writeStream
        .format("memory")
        .queryName("sensor_violations")
        .outputMode("update")
        .option("checkpointLocation", checkpoint_dir)
        .trigger(availableNow=True)
        .start())
    query.awaitTermination()

    return spark.table("sensor_violations")


# ---- Test harness ----
if __name__ == "__main__":
    import json
    import os
    import shutil
    import tempfile

    spark = (SparkSession.builder
        .appName("StreamingTest")
        .master("local[*]")
        .config("spark.sql.shuffle.partitions", "4")
        .getOrCreate())

    wc = streaming_word_count(spark)
    assert wc is not None, "streaming_word_count returned None"
    top_word = wc.collect()[0]
    assert top_word["word"] in ("spark", "hello", "world"), f"Unexpected top word: {top_word}"
    print("Word counts:")
    wc.show(truncate=False)

    ww = streaming_windowed_count(spark)
    assert ww is not None, "streaming_windowed_count returned None"
    assert "window" in ww.columns, "Missing window column"
    print("\nWindowed word counts:")
    ww.show(truncate=False)

    tmp = tempfile.mkdtemp()
    try:
        input_dir = os.path.join(tmp, "readings")
        os.makedirs(input_dir)
        readings = [
            ("s1", 50, "2024-01-01 12:00:00"),
            ("s1", 120, "2024-01-01 12:03:00"),
            ("s2", 130, "2024-01-01 12:04:00"),
            ("s1", 150, "2024-01-01 12:11:00"),
            ("s2", 20, "2024-01-01 12:12:00"),
        ]
        with open(os.path.join(input_dir, "batch-0001.json"), "w") as fh:
            for sensor, temp, ts in readings:
                fh.write(json.dumps({"sensor": sensor, "temp": temp, "event_time": ts}) + "\n")

        windows = sensor_window_stream(spark, input_dir, os.path.join(tmp, "ck_windows"))
        assert windows is not None, "sensor_window_stream returned None"
        assert windows.count() == 4, f"Expected 4 (window, sensor) rows, got {windows.count()}"
        first_window_s1 = (windows
            .filter((f.col("sensor") == "s1") & (f.col("window.start") == datetime(2024, 1, 1, 12, 0)))
            .first())
        assert first_window_s1["max_temp"] == 120, f"Wrong max_temp for s1 12:00-12:10: {first_window_s1}"
        print("\nStreaming windows (memory sink):")
        windows.orderBy("window", "sensor").show(truncate=False)

        violations = sensor_violations(spark, input_dir, os.path.join(tmp, "ck_violations"))
        assert violations is not None, "sensor_violations returned None"
        got = {r["sensor"]: r["violations"] for r in violations.collect()}
        assert got == {"s1": 2, "s2": 1}, f"Expected s1=2, s2=1 violations, got {got}"
        print("transformWithState violations (memory sink):")
        violations.orderBy("sensor").show()

        print("All tests passed!")
    finally:
        for q in spark.streams.active:
            q.stop()
        shutil.rmtree(tmp, ignore_errors=True)
        spark.stop()
