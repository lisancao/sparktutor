"""
Images and Audio - Solution

1. read_images: the image source over a folder tree, every file kept, with
   a valid flag and the file size joined from binaryFile
2. color_means: average red, green and blue per valid image, computed by
   an Arrow UDF over the decoded pixels (stored in BGR order)
3. wav_info: sample rate, channels, duration and loudness (RMS) per WAV
   file, parsed with the standard library in a Python UDF
4. audio_windows: one row per 50 ms window with its peak level, using
   mapInArrow (one file in, many rows out)
5. stream_batch_sizes: a streaming binaryFile query that takes one file
   per micro-batch
"""

from pyspark.sql import SparkSession, functions as F

COLOR_TYPE = "struct<r:double, g:double, b:double>"
WAV_TYPE = "struct<rate:int, channels:int, seconds:double, rms:double>"
WINDOW_SCHEMA = "file string, window int, peak double"
BINARY_FILE_SCHEMA = "path string, modificationTime timestamp, length long, content binary"


def bgr_to_rgb_means(data, channels):
    """Mean (r, g, b) of one decoded image, or None if it is not valid.

    The image source stores pixels row by row as B, G, R (and A when the
    image has an alpha channel), one byte each; gray images have one byte
    per pixel.
    """
    import numpy as np

    if data is None or channels is None or channels < 1:
        return None
    pixels = np.frombuffer(data, dtype=np.uint8).reshape(-1, channels).astype(float)
    if channels == 1:
        gray = float(pixels[:, 0].mean())
        return {"r": gray, "g": gray, "b": gray}
    return {"r": float(pixels[:, 2].mean()), "g": float(pixels[:, 1].mean()),
            "b": float(pixels[:, 0].mean())}


def wav_bytes_info(content):
    """(rate, channels, seconds, rms) of a 16-bit PCM WAV file, rms in 0..1."""
    import array
    import io
    import math
    import wave

    with wave.open(io.BytesIO(content)) as w:
        rate, channels, frames = w.getframerate(), w.getnchannels(), w.getnframes()
        samples = array.array("h", w.readframes(frames))
    rms = math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768 if samples else 0.0
    return (rate, channels, frames / rate, rms)


def read_images(spark, folder):
    """Every file under folder: file, valid, width, height, channels, mode, bytes, data."""
    images = (spark.read.format("image")
              .option("recursiveFileLookup", "true")
              .load(folder)
              .select(F.col("_metadata.file_path").alias("file_path"),
                      F.col("_metadata.file_name").alias("file"),
                      (F.col("image.nChannels") > 0).alias("valid"),
                      F.col("image.width").alias("width"),
                      F.col("image.height").alias("height"),
                      F.col("image.nChannels").alias("channels"),
                      F.col("image.mode").alias("mode"),
                      F.col("image.data").alias("data")))
    # image.origin is file:///..., binaryFile's path is file:/...;
    # _metadata.file_path has the same form in both sources
    sizes = (spark.read.format("binaryFile")
             .option("recursiveFileLookup", "true")
             .load(folder)
             .select(F.col("_metadata.file_path").alias("file_path"),
                     F.col("length").alias("bytes")))
    return (images.join(sizes, "file_path")
            .select("file", "valid", "width", "height", "channels", "mode", "bytes", "data"))


def color_means(images):
    """Valid images only: file, width, height, r, g, b."""
    import pyarrow as pa

    struct_type = pa.struct([("r", pa.float64()), ("g", pa.float64()), ("b", pa.float64())])

    @F.arrow_udf(COLOR_TYPE)
    def rgb_means(data: pa.Array, channels: pa.Array) -> pa.Array:
        out = [bgr_to_rgb_means(d, c) for d, c in zip(data.to_pylist(), channels.to_pylist())]
        return pa.array(out, type=struct_type)

    return (images.filter("valid")
            .select("file", "width", "height", rgb_means("data", "channels").alias("c"))
            .select("file", "width", "height", "c.r", "c.g", "c.b"))


def wav_info(spark, folder):
    """One row per WAV file: file, rate, channels, seconds, rms."""
    info = F.udf(wav_bytes_info, WAV_TYPE)
    return (spark.read.format("binaryFile").option("pathGlobFilter", "*.wav").load(folder)
            .select(F.col("_metadata.file_name").alias("file"), info("content").alias("w"))
            .select("file", "w.*"))


def wav_windows(batches, window_ms=50):
    """mapInArrow function: one output row per window of every input file."""
    import array
    import io
    import wave

    import pyarrow as pa

    for batch in batches:
        files, windows, peaks = [], [], []
        for name, content in zip(batch.column("file").to_pylist(), batch.column("content").to_pylist()):
            with wave.open(io.BytesIO(content)) as w:
                rate = w.getframerate()
                samples = array.array("h", w.readframes(w.getnframes()))
            step = rate * window_ms // 1000
            for i in range(0, len(samples), step):
                chunk = samples[i:i + step]
                files.append(name)
                windows.append(i // step)
                peaks.append(max(abs(s) for s in chunk) / 32768)
        # window is declared int: build an int32 array, not Python's default int64
        yield pa.RecordBatch.from_arrays(
            [pa.array(files, pa.string()), pa.array(windows, pa.int32()), pa.array(peaks, pa.float64())],
            names=["file", "window", "peak"])


def audio_windows(spark, folder):
    """One row per 50 ms window: file, window, peak."""
    raw = (spark.read.format("binaryFile").option("pathGlobFilter", "*.wav").load(folder)
           .select(F.col("_metadata.file_name").alias("file"), "content"))
    return raw.mapInArrow(wav_windows, WINDOW_SCHEMA)


def stream_batch_sizes(spark, folder, checkpoint):
    """Stream folder with binaryFile, one file per micro-batch; return rows per batch."""
    query = (spark.readStream.format("binaryFile")
             .schema(BINARY_FILE_SCHEMA)
             .option("pathGlobFilter", "*.wav")
             .option("maxFilesPerTrigger", 1)
             .load(folder)
             .select("path", "length")
             .writeStream.format("memory").queryName("incoming_audio")
             .option("checkpointLocation", checkpoint)
             .trigger(availableNow=True)
             .start())
    query.awaitTermination()
    return [p.numInputRows for p in query.recentProgress if p.numInputRows > 0]


# ---- Test harness ----
if __name__ == "__main__":
    import tempfile

    spark = (SparkSession.builder
             .appName("ImagesAndAudio")
             .master("local[*]")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    try:
        # 1. Images, valid and invalid
        images = read_images(spark, "data/messy/images")
        assert images is not None, "read_images() returned None"
        expected_cols = ["file", "valid", "width", "height", "channels", "mode", "bytes", "data"]
        assert images.columns == expected_cols, f"read_images columns should be {expected_cols}, got {images.columns}"
        images = images.cache()
        rows = {r["file"]: r for r in images.collect()}
        assert len(rows) == 6, (
            f"Expected all 6 files under images/ (keep invalid ones, read subfolders), got {sorted(rows)}. "
            "Use recursiveFileLookup, do not set dropInvalid, and join the sizes on "
            "_metadata.file_path (image.origin and binaryFile's path are written differently)")
        invalid = sorted(n for n, r in rows.items() if not r["valid"])
        assert invalid == ["corrupt.png", "readme.txt"], f"Invalid files should be corrupt.png and readme.txt, got {invalid}"
        channels = {n: (r["channels"], r["mode"]) for n, r in rows.items() if r["valid"]}
        assert channels == {"red_16x8.png": (3, 16), "gradient_32x32.png": (3, 16),
                            "logo_rgba_12x12.png": (4, 24), "gray_20x10.png": (1, 0)}, (
            f"(nChannels, mode) per valid image is wrong: {channels}")
        assert rows["red_16x8.png"]["bytes"] == 76 and rows["corrupt.png"]["bytes"] == 24, (
            "bytes should be the file size (binaryFile's length column): red_16x8.png is 76 bytes, "
            f"corrupt.png 24; got {rows['red_16x8.png']['bytes']} and {rows['corrupt.png']['bytes']}")
        red = rows["red_16x8.png"]
        assert len(red["data"]) == red["width"] * red["height"] * red["channels"], "data should hold width*height*channels bytes"
        assert bytes(red["data"][:3]) == b"\x00\x00\xff", (
            f"A red pixel is stored as B, G, R = 00 00 ff; got {bytes(red['data'][:3]).hex(' ')}")

        # 2. Colors
        colors = color_means(images)
        assert colors is not None, "color_means() returned None"
        assert colors.columns == ["file", "width", "height", "r", "g", "b"], (
            f"color_means columns should be file, width, height, r, g, b; got {colors.columns}")
        got = {r["file"]: (round(r["r"], 2), round(r["g"], 2), round(r["b"], 2)) for r in colors.collect()}
        expected = {"red_16x8.png": (255.0, 0.0, 0.0), "gradient_32x32.png": (124.0, 124.0, 128.0),
                    "logo_rgba_12x12.png": (0.0, 0.0, 255.0), "gray_20x10.png": (114.0, 114.0, 114.0)}
        assert got == expected, (
            f"Mean (r, g, b) per valid image should be\n  {expected}\ngot\n  {got}\n"
            "If red and blue are swapped, remember the bytes are B, G, R. Skip the alpha byte.")

        # 3. WAV metadata
        info = wav_info(spark, "data/messy/audio")
        assert info is not None, "wav_info() returned None"
        assert info.columns == ["file", "rate", "channels", "seconds", "rms"], (
            f"wav_info columns should be file, rate, channels, seconds, rms; got {info.columns}")
        wav = {r["file"]: r for r in info.collect()}
        durations = {n: r["seconds"] for n, r in wav.items()}
        assert durations == {"tone_440.wav": 0.25, "tone_880_quiet.wav": 0.25, "silence.wav": 0.5}, (
            f"Durations should be frames / rate: 0.25, 0.25 and 0.5 seconds; got {durations}")
        assert all(r["rate"] == 8000 and r["channels"] == 1 for r in wav.values()), "All files are 8000 Hz mono"
        assert wav["silence.wav"]["rms"] == 0.0, f"silence.wav should have RMS 0, got {wav['silence.wav']['rms']}"
        assert abs(wav["tone_440.wav"]["rms"] - 0.3535) < 0.001, (
            f"A sine wave at amplitude 0.5 has RMS 0.5/sqrt(2) = 0.354; got {wav['tone_440.wav']['rms']}")
        assert wav["tone_880_quiet.wav"]["rms"] < wav["tone_440.wav"]["rms"] / 5, "The quiet tone should be much quieter"

        # 4. Windows
        windows = audio_windows(spark, "data/messy/audio")
        assert windows is not None, "audio_windows() returned None"
        assert dict(windows.dtypes) == {"file": "string", "window": "int", "peak": "double"}, (
            f"audio_windows schema should be {WINDOW_SCHEMA}, got {windows.dtypes}")
        per_file = {r["file"]: (r["n"], round(r["peak"], 3)) for r in
                    windows.groupBy("file").agg(F.count("*").alias("n"), F.max("peak").alias("peak")).collect()}
        assert per_file == {"tone_440.wav": (5, 0.5), "tone_880_quiet.wav": (5, 0.05), "silence.wav": (10, 0.0)}, (
            f"(windows, loudest peak) per file should be tone_440 (5, 0.5), tone_880_quiet (5, 0.05), "
            f"silence (10, 0.0); got {per_file}")

        # 5. Streaming, one file per batch
        checkpoint = tempfile.mkdtemp(prefix="audio_ckpt_")
        sizes = stream_batch_sizes(spark, "data/messy/audio", checkpoint)
        assert sizes == [1, 1, 1], (
            f"With maxFilesPerTrigger 1, three files should arrive in three batches of 1; got {sizes}")
        assert spark.table("incoming_audio").count() == 3, "The memory sink should hold 3 rows"

        print("Images:")
        images.drop("data").orderBy("file").show()
        print("Colors:")
        colors.orderBy("file").show()
        print("WAV files:")
        info.orderBy("file").show()
        print("Windows of tone_440.wav:")
        windows.filter("file = 'tone_440.wav'").orderBy("window").show()
        print("Streaming batch sizes:", sizes)
        print("All tests passed!")
    finally:
        spark.stop()
