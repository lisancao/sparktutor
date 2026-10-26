"""
Files as Files - Solution

Build a file inventory with the binaryFile source: what kind of file each
one really is (from its first bytes, not its name), how big it is, a SHA-256
for finding duplicates, and the width and height of every valid PNG, read
straight out of the PNG header.
"""

from pyspark.sql import SparkSession, functions as F

PNG_MAGIC = "89504E470D0A1A0A"  # \x89 P N G \r \n \x1a \n
IHDR = "49484452"               # the ASCII letters I H D R


def head_hex(start, n):
    """Hex string of n bytes of `content`, starting at byte `start` (1-based)."""
    return F.hex(F.substring("content", start, n))


def be_uint32(start):
    """The 4-byte big-endian unsigned integer at byte `start`, as a long."""
    return F.conv(head_hex(start, 4), 16, 10).cast("long")


def inventory(spark, paths):
    """One row per file under `paths` (searched recursively).

    Columns: path, file_name, length, sha256, kind ("png", "wav", "pdf" or
    "other"), png_ok (true or false for PNGs, NULL otherwise), png_width and
    png_height (NULL unless png_ok).
    """
    files = (spark.read.format("binaryFile")
             .option("recursiveFileLookup", "true")
             .load(paths))

    kind = (F.when(head_hex(1, 8) == PNG_MAGIC, "png")
            .when((head_hex(1, 4) == "52494646") & (head_hex(9, 4) == "57415645"), "wav")  # RIFF....WAVE
            .when(head_hex(1, 5) == "255044462D", "pdf")                                   # %PDF-
            .otherwise("other"))

    # A real PNG has its IHDR chunk right after the 8-byte signature
    png_ok = F.when(kind == "png", head_hex(13, 4) == IHDR)

    return (files
            .withColumn("kind", kind)
            .withColumn("png_ok", png_ok)
            .select(
                "path",
                F.col("_metadata.file_name").alias("file_name"),
                "length",
                F.sha2("content", 256).alias("sha256"),
                "kind",
                "png_ok",
                F.when(F.col("png_ok"), be_uint32(17)).alias("png_width"),
                F.when(F.col("png_ok"), be_uint32(21)).alias("png_height"),
            ))


def duplicates(inv):
    """Groups of files with identical content: sha256, n, files (sorted names)."""
    return (inv.groupBy("sha256")
            .agg(F.count("*").alias("n"),
                 F.sort_array(F.collect_list("file_name")).alias("files"))
            .filter(F.col("n") > 1))


def recent_files(spark, folder, since):
    """path and length of the files in `folder` modified after `since`."""
    return (spark.read.format("binaryFile")
            .option("modifiedAfter", since)
            .load(folder)
            .select("path", "length"))


def sizes_only(spark, folder):
    """path, file_name and length for every file in `folder`, without reading content."""
    return (spark.read.format("binaryFile")
            .load(folder)
            .select("path", F.col("_metadata.file_name").alias("file_name"), "length"))


# ---- Test harness ----
if __name__ == "__main__":
    import os
    import shutil
    import tempfile

    spark = (SparkSession.builder
             .appName("FilesAsFiles")
             .master("local[*]")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    # A pretend upload folder: one fresh copy of a product image, and one
    # old copy of a recording (its modification time set back to 2020)
    uploads = tempfile.mkdtemp(prefix="uploads_")
    shutil.copy("data/messy/images/products/red_16x8.png", os.path.join(uploads, "upload_0001.png"))
    old = os.path.join(uploads, "voice_note.wav")
    shutil.copy("data/messy/audio/tone_440.wav", old)
    os.utime(old, (1577836800, 1577836800))  # 2020-01-01 00:00:00 UTC

    paths = ["data/messy/images", "data/messy/audio", "data/messy/pdf", "data/messy/mail", uploads]

    try:
        inv = inventory(spark, paths)
        assert inv is not None, "inventory() returned None: complete TODOs 1 to 4"
        expected_cols = ["path", "file_name", "length", "sha256", "kind", "png_ok", "png_width", "png_height"]
        assert inv.columns == expected_cols, f"inventory columns should be {expected_cols}, got {inv.columns}"
        inv = inv.cache()
        rows = {r["file_name"]: r for r in inv.collect()}

        assert len(rows) == 17, (
            f"Expected 17 files, found {len(rows)}: {sorted(rows)}. images/ holds only subfolders, "
            "so you need option('recursiveFileLookup', 'true')")

        kinds = {r["kind"]: r["n"] for r in inv.groupBy("kind").agg(F.count("*").alias("n")).collect()}
        assert kinds == {"png": 6, "wav": 4, "pdf": 2, "other": 5}, (
            f"Files per kind should be png 6, wav 4, pdf 2, other 5; got {kinds}. "
            "Decide the kind from the first bytes (hex of substring), not from the file name")

        assert rows["readme.txt"]["kind"] == "other", "readme.txt is text, not an image"
        assert rows["corrupt.png"]["kind"] == "png", "corrupt.png starts with the PNG signature, so its kind is png"
        assert rows["corrupt.png"]["png_ok"] is False, (
            "corrupt.png has the PNG signature but no IHDR chunk at bytes 13-16: png_ok must be False")
        assert rows["corrupt.png"]["png_width"] is None, "Don't report a width for an invalid PNG"
        assert rows["tone_440.wav"]["png_ok"] is None, "png_ok should be NULL for files that are not PNGs"

        sizes = {n: (rows[n]["png_width"], rows[n]["png_height"])
                 for n in ["red_16x8.png", "gradient_32x32.png", "logo_rgba_12x12.png", "gray_20x10.png"]}
        assert sizes == {"red_16x8.png": (16, 8), "gradient_32x32.png": (32, 32),
                         "logo_rgba_12x12.png": (12, 12), "gray_20x10.png": (20, 10)}, (
            f"PNG width and height are wrong: {sizes}. Width is bytes 17-20 and height bytes 21-24, "
            "big-endian: conv(hex(substring(content, 17, 4)), 16, 10)")

        assert len(rows["red_16x8.png"]["sha256"] or "") == 64, "sha256 should be sha2(content, 256), 64 hex characters"

        dups = duplicates(inv)
        assert dups is not None, "duplicates() returned None: complete TODO 5"
        groups = sorted(r["files"] for r in dups.collect())
        assert groups == [["red_16x8.png", "upload_0001.png"], ["tone_440.wav", "voice_note.wav"]], (
            f"Expected two duplicate groups (the copied PNG and the copied WAV), got {groups}")

        recent = recent_files(spark, uploads, "2025-01-01T00:00:00")
        assert recent is not None, "recent_files() returned None: complete TODO 6"
        recent_names = sorted(os.path.basename(r["path"]) for r in recent.collect())
        assert recent_names == ["upload_0001.png"], (
            f"Only upload_0001.png was modified after 2025; got {recent_names}. Use option('modifiedAfter', since)")

        # With a tiny maxLength, reading content fails but path and length still work
        spark.conf.set("spark.sql.sources.binaryFile.maxLength", "1000")
        try:
            listing = sizes_only(spark, "data/messy/audio")
            assert listing is not None, "sizes_only() returned None: complete TODO 7"
            assert "content" not in listing.columns, "sizes_only must not select the content column"
            audio = sorted((r["file_name"], r["length"]) for r in listing.collect())
            assert audio == [("silence.wav", 8044), ("tone_440.wav", 4044), ("tone_880_quiet.wav", 4044)], (
                f"Unexpected audio listing {audio}")
            try:
                spark.read.format("binaryFile").load("data/messy/audio").select("content").collect()
                raise AssertionError("Reading content over maxLength should have failed")
            except AssertionError:
                raise
            except Exception as e:  # noqa: BLE001
                assert "exceeds the max length" in str(e), f"Unexpected error: {e}"
        finally:
            spark.conf.unset("spark.sql.sources.binaryFile.maxLength")

        print("Inventory:")
        inv.select("file_name", "length", "kind", "png_ok", "png_width", "png_height",
                   F.substring("sha256", 1, 12).alias("sha256")).orderBy("kind", "file_name").show(20, truncate=False)
        print("Duplicates:")
        dups.select(F.substring("sha256", 1, 12).alias("sha256"), "n", "files").show(truncate=False)
        print("Uploads modified after 2025:", recent_names)
        print("Audio sizes, read with maxLength=1000 and no content column:", audio)
        print("All tests passed!")
    finally:
        shutil.rmtree(uploads, ignore_errors=True)
        spark.stop()
