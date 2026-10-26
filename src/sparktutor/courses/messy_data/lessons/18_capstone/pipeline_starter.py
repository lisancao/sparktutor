"""
Capstone, part 2: A Multimodal Catalog Pipeline - Starter Code

A Declarative Pipeline that builds the same catalog as the `docs` data
source, from built-in sources and Python UDFs only. Python data sources
are left out on purpose: on Spark 4.2.0 a pipeline that uses one makes
spark-pipelines exit with status 1 even when every flow completes
(SPARK-59135, fixed in 4.4.0), and SparkTutor grades pipelines by exit
status.

    files_inventory   bronze  one row per file: binaryFile without content
    images            silver  valid images only (image source, dropInvalid)
    audio             silver  WAV duration with a UDF
    doc_parts         silver  PDF pages, e-mails and text files with a UDF
    catalog           gold    one row per document part, every file present
    check_*                   assert_true checks; a failure fails the run
"""

import os

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

spark: SparkSession

DATA = os.path.abspath("data/messy")
KINDS = {".png": "image", ".wav": "audio", ".pdf": "pdf", ".eml": "email",
         ".md": "text", ".txt": "text", ".log": "log", ".json": "json", ".xml": "xml"}
EXTENSION = F.lower(F.regexp_extract(F.col("path"), r"(\.[A-Za-z0-9]+)$", 1))
KIND = F.coalesce(F.create_map(*[F.lit(x) for kv in KINDS.items() for x in kv])[EXTENSION], F.lit("other"))

PART_TYPE = "array<struct<part:int, title:string, text:string>>"


# ---- UDFs (standard library only) ----
@F.udf("double")
def wav_seconds(content):
    import io
    import wave

    with wave.open(io.BytesIO(content)) as w:
        return w.getnframes() / w.getframerate()


@F.udf(PART_TYPE)
def split_parts(kind, content):
    """One entry per part: PDF pages, an e-mail, or a whole text file."""
    import re
    from email import policy
    from email.parser import BytesParser

    if kind == "pdf":
        pages = re.findall(rb"BT .*?\((.*?)\) Tj ET", content, re.S)
        return [(n, None, t.decode("latin-1")) for n, t in enumerate(pages, 1)]
    if kind == "email":
        msg = BytesParser(policy=policy.default).parsebytes(content)
        body = msg.get_body(("plain",))
        return [(0, str(msg["Subject"]), body.get_content().strip() if body else None)]
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    first = text.splitlines()[0] if text else ""
    return [(0, first.lstrip("# ").strip() or None, text)]


# ---- Bronze ----
@dp.materialized_view(comment="Every file under data/messy, without its bytes")
def files_inventory() -> DataFrame:
    return (spark.read.format("binaryFile")
            .option("recursiveFileLookup", "true")
            .load(DATA)
            .select(F.col("_metadata.file_path").alias("path"),
                    F.col("_metadata.file_name").alias("file_name"),
                    F.col("length").alias("size"),
                    "modificationTime")
            .withColumn("kind", KIND))


# ---- Silver ----
# TODO 1: images, a materialized view over f"{DATA}/images" read with
#   format("image"), options dropInvalid and recursiveFileLookup set to
#   "true", selecting _metadata.file_path AS path, image.width AS width,
#   image.height AS height and image.nChannels AS channels.
#   (Join on _metadata.file_path: image.origin uses a different URI form.)


@dp.materialized_view(comment="WAV durations")
def audio() -> DataFrame:
    return (spark.read.format("binaryFile")
            .option("pathGlobFilter", "*.wav")
            .load(f"{DATA}/audio")
            .select(F.col("_metadata.file_path").alias("path"),
                    wav_seconds("content").alias("seconds")))


# TODO 2: doc_parts, a materialized view with one row per part:
#   - binaryFile over DATA with recursiveFileLookup "true"
#   - select _metadata.file_path AS path and content, add kind = KIND
#   - keep kinds pdf, email, text, log, json, xml
#   - explode(split_parts("kind", "content")) and select
#     path, kind, p.part, p.title, p.text


# ---- Gold ----
# TODO 3: catalog, a materialized view: files_inventory LEFT JOIN doc_parts
#   (select path, part, title, text from it; do not use drop(), see the
#   lesson), then LEFT JOIN images and audio on path. Select path,
#   file_name, kind, coalesce(part, 0) AS part, size, width, height,
#   seconds, title, text.


# ---- Checks (do not modify below this line) ----
def _expect(table: str, condition: str, message: str) -> DataFrame:
    df = spark.read.table(table)
    return df.agg(F.expr(condition).alias("ok")).select(
        F.assert_true(F.col("ok"), f"{table}: {message}").alias("ok"))


@dp.materialized_view
def check_inventory() -> DataFrame:
    return _expect(
        "files_inventory",
        "count(*) = 26 AND count_if(kind = 'image') = 5 AND count_if(kind = 'pdf') = 2 "
        "AND count_if(kind = 'email') = 4 AND count_if(kind = 'text') = 6 "
        "AND count_if(kind = 'other') = 0",
        "expected 26 files: 5 images, 2 PDFs, 4 e-mails, 6 text files and no unknown kinds")


@dp.materialized_view
def check_images_valid() -> DataFrame:
    return _expect(
        "images",
        "count(*) = 4 AND min(width) > 0 AND count_if(path LIKE '%corrupt.png') = 0 "
        "AND count_if(path LIKE '%.txt') = 0",
        "expected the 4 decodable PNGs and no corrupt or non-image file")


@dp.materialized_view
def check_audio() -> DataFrame:
    return _expect(
        "audio",
        "count(*) = 3 AND sort_array(collect_list(seconds)) = array(0.25D, 0.25D, 0.5D)",
        "expected 3 WAV files of 0.25, 0.25 and 0.5 seconds")


@dp.materialized_view
def check_pdf_pages() -> DataFrame:
    return _expect(
        "doc_parts",
        "count_if(kind = 'pdf') = 3 "
        "AND count_if(kind = 'pdf' AND path LIKE '%invoice_1001.pdf' AND part = 2) = 1 "
        "AND count_if(kind = 'pdf' AND text = 'Invoice 1002 total 17.00 CAD') = 1",
        "expected every PDF page: 2 pages of invoice_1001.pdf and 1 of invoice_1002.pdf")


@dp.materialized_view
def check_catalog() -> DataFrame:
    return _expect(
        "catalog",
        "count(*) = 27 AND count(DISTINCT path) = 26 "
        "AND count_if(kind = 'image' AND width IS NULL) = 1 "
        "AND count_if(kind = 'email' AND title IS NULL) = 0",
        "expected 27 parts from all 26 files, with only corrupt.png lacking a width")
