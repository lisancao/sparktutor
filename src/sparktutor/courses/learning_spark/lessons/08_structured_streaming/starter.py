"""
Structured Streaming - Starter Code

Implement the `streaming_word_count` function that:
1. Creates a batch DataFrame simulating streaming text data
2. Splits lines into individual words using split + explode
3. Groups by word and counts occurrences
4. Orders by count descending
5. Returns the word count DataFrame

This exercise simulates a streaming word count in batch mode
(dry-run compatible — no actual stream needed).

In a real streaming scenario, you would replace spark.createDataFrame
with spark.readStream.format("socket") or .format("kafka").
"""

from pyspark.sql import SparkSession, functions as f
from pyspark.sql.types import StructType, StructField, StringType


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


def streaming_word_count(spark):
    """Simulate a streaming word count in batch mode."""

    lines_df = spark.createDataFrame(TEXT_DATA, SCHEMA)

    # TODO: Split each line into words using split() and explode()
    #       Create a column called "word"
    words_df = None  # Replace

    # TODO: Group by word and count occurrences
    counts_df = None  # Replace

    # TODO: Order by count descending
    result = None  # Replace

    return result


def streaming_windowed_count(spark):
    """Demonstrate windowed aggregation concepts in batch mode.

    Creates timestamped word data, applies a time-based window,
    and counts words per window.
    """
    from pyspark.sql.types import TimestampType
    from datetime import datetime, timedelta

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

    # TODO: Split lines into words with timestamps preserved
    words_df = None  # Replace

    # TODO: Group by 10-minute tumbling window on event_time and word,
    #       count occurrences
    #       Use: f.window("event_time", "10 minutes")
    windowed_counts = None  # Replace

    return windowed_counts


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("StreamingTest")
        .master("local[*]")
        .getOrCreate())

    # Test 1: Basic word count
    wc = streaming_word_count(spark)
    assert wc is not None, "streaming_word_count returned None"
    top_word = wc.collect()[0]
    assert top_word["word"] in ("spark", "hello", "world"), f"Unexpected top word: {top_word}"
    print("Word counts:")
    wc.show(truncate=False)

    # Test 2: Windowed count
    ww = streaming_windowed_count(spark)
    assert ww is not None, "streaming_windowed_count returned None"
    assert "window" in ww.columns, "Missing window column"
    print("\nWindowed word counts:")
    ww.show(truncate=False)

    print("All tests passed!")
    spark.stop()
