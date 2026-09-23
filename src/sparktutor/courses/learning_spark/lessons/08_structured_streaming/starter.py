"""
Structured Streaming - 起始代码

实现 `streaming_word_count` 函数：
1. 创建模拟流式文本数据的批量 DataFrame
2. 使用 split + explode 将每行拆分为单个单词
3. 按单词分组并计数
4. 按计数降序排列
5. 返回单词计数 DataFrame

本练习以批处理模式模拟流式单词计数
（兼容 dry-run — 无需实际流）。

在真实流式场景中，你可以将 spark.createDataFrame
替换为 spark.readStream.format("socket") 或 .format("kafka")。
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
    """以批处理模式模拟流式单词计数。"""

    lines_df = spark.createDataFrame(TEXT_DATA, SCHEMA)

    # TODO: 使用 split() 和 explode() 将每行拆分为单词
    #       创建名为 "word" 的列
    words_df = None  # 替换

    # TODO: 按单词分组并计数
    counts_df = None  # 替换

    # TODO: 按计数降序排列
    result = None  # 替换

    return result


def streaming_windowed_count(spark):
    """以批处理模式演示窗口聚合概念。

    创建带时间戳的单词数据，应用基于时间的窗口，
    并统计每个窗口内的单词数。
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

    # TODO: 将行拆分为单词，保留时间戳
    words_df = None  # 替换

    # TODO: 按 event_time 上 10 分钟的滚动窗口和单词分组，
    #       统计出现次数
    #       使用：f.window("event_time", "10 minutes")
    windowed_counts = None  # 替换

    return windowed_counts


# ---- 测试代码（请勿修改此行以下内容）----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("StreamingTest")
        .master("local[*]")
        .getOrCreate())

    # 测试 1：基础单词计数
    wc = streaming_word_count(spark)
    assert wc is not None, "streaming_word_count 返回了 None"
    top_word = wc.collect()[0]
    assert top_word["word"] in ("spark", "hello", "world"), f"意外的排名第一的单词：{top_word}"
    print("单词计数：")
    wc.show(truncate=False)

    # 测试 2：窗口计数
    ww = streaming_windowed_count(spark)
    assert ww is not None, "streaming_windowed_count 返回了 None"
    assert "window" in ww.columns, "缺少 window 列"
    print("\n窗口单词计数：")
    ww.show(truncate=False)

    print("所有测试通过！")
    spark.stop()
