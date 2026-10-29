# spark-connectors: delta
"""
Designing Tables for Blobs - Exercise

A content-addressed media catalog in Delta Lake: small files inline, large
files in a content-addressed store, one row per distinct content, a sources
table that maps every file path to its content, derived artifacts keyed by
hash, compaction after many small ingests, and an end-to-end "forget this
file" that leaves no copy of its bytes anywhere in the tables.
"""

import os

from pyspark.sql import SparkSession, functions as sf

INLINE_LIMIT = 64 * 1024        # bytes; larger files go to the content-addressed store
EXTRACTOR = "headers-v1"        # version of the code that computes derived artifacts
TEXT_TYPES = {".md": "text/markdown", ".txt": "text/plain", ".eml": "message/rfc822"}


def create_tables(spark, tables):
    """Create the three Delta tables (by path) if they don't exist.

    tables["blobs"]:   content_hash, media_type, size, content (inline or NULL), blob_uri (CAS or NULL)
    tables["sources"]: uri, content_hash, size
    tables["derived"]: content_hash, artifact, extractor, value
    All three are clustered by content_hash (sources by uri) and have deletion vectors on.
    """
    # TODO: CREATE TABLE IF NOT EXISTS delta.`<path>` ... USING delta CLUSTER BY (...) TBLPROPERTIES (...)
    pass


def scan(spark, root):
    """Every file under `root` as (uri, content_hash, media_type, size, content).

    media_type: from magic bytes for PNG (89 50 4E 47), WAV (RIFF....WAVE)
    and PDF (%PDF), then from the extension for .md, .txt and .eml, else
    application/octet-stream.
    """
    # TODO: binaryFile with recursiveFileLookup, sha2(content, 256), media type from magic bytes
    return None


def cas_path(cas_root, content_hash):
    """Where a large blob lives: <cas_root>/<first 2 hex chars>/<hash>."""
    return os.path.join(cas_root, content_hash[:2], content_hash)


def ingest(spark, scanned, tables, cas_root, inline_limit=INLINE_LIMIT):
    """Add scanned files to the catalog. Safe to run again on the same files.

    1. Write each distinct large content to the CAS (skip if already there).
    2. MERGE one row per new content_hash into blobs (inline content only
       up to inline_limit, blob_uri otherwise).
    3. MERGE every uri into sources (insert new paths, repoint changed ones).
    """
    # TODO: store large contents in the CAS, then MERGE into blobs and sources
    pass


def derive(spark, tables):
    """Compute derived artifacts for blobs that don't have them yet.

    - png_size: "<width>x<height>" from the IHDR chunk of an inline PNG
      (bytes 17-24, big-endian), only when bytes 13-16 are "IHDR"
    - wav_rate: the sample rate from bytes 25-28 (little-endian) of an inline WAV
    Rows carry `extractor` so a new version can be recomputed later.
    """
    # TODO: compute candidates, anti-join what exists, MERGE the rest
    pass


def forget(spark, tables, uri, cas_root):
    """Remove one source file from the catalog, everywhere. Return True if its content went too.

    Delete the uri from sources. If no other uri still points at its
    content_hash, delete the blob row, its derived rows and its CAS file.
    Deletion vectors only mark rows as deleted, so purge them (REORG ...
    APPLY (PURGE)) and VACUUM with zero retention, or the bytes stay on disk.
    """
    # TODO: delete everywhere, then purge deletion vectors and vacuum
    return None


def compact(spark, table_path):
    """Compact the small files left by many small ingests."""
    # TODO
    pass


# ---- Test harness ----
if __name__ == "__main__":
    import glob
    import hashlib
    import random
    import shutil
    import struct
    import tempfile

    spark = (SparkSession.builder
        .appName("BlobTableDesign")
        .master("local[2]")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate())
    spark.sparkContext.setLogLevel("OFF")

    work = tempfile.mkdtemp(prefix="blob_tables_")
    try:
        # An incoming folder: the sample media, two large files and a duplicate
        incoming = os.path.join(work, "incoming")
        for folder in ["images", "audio", "pdf", "docs", "mail"]:
            shutil.copytree(os.path.join("data/messy", folder), os.path.join(incoming, folder))
        os.makedirs(os.path.join(incoming, "large"))
        rng = random.Random(47)
        for name, size in [("scan_a.bin", 200_000), ("scan_b.bin", 300_000)]:
            with open(os.path.join(incoming, "large", name), "wb") as f:
                f.write(bytes(rng.getrandbits(8) for _ in range(size)))
        shutil.copy(os.path.join(incoming, "images/products/red_16x8.png"),
                    os.path.join(incoming, "large", "red_copy.png"))

        # Expected catalog, computed with plain Python
        def media_type(path, data):
            if data[:4] == b"\x89PNG":
                return "image/png"
            if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
                return "audio/wav"
            if data[:4] == b"%PDF":
                return "application/pdf"
            return TEXT_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")

        expected = {}
        for path in glob.glob(os.path.join(incoming, "**", "*"), recursive=True):
            if os.path.isfile(path):
                data = open(path, "rb").read()
                expected["file:" + path] = (hashlib.sha256(data).hexdigest(), media_type(path, data), data)
        hashes = {h for h, _, _ in expected.values()}

        tables = {n: os.path.join(work, "tables", n) for n in ["blobs", "sources", "derived"]}
        cas_root = os.path.join(work, "cas")
        create_tables(spark, tables)
        for name, path in tables.items():
            assert os.path.isdir(os.path.join(path, "_delta_log")), (
                f"create_tables did not create the {name} table at {path} (no _delta_log folder)")
            detail = spark.sql(f"DESCRIBE DETAIL delta.`{path}`").first()
            assert detail is not None and detail.format == "delta", f"{name} is not a Delta table at {path}"
            want = ["uri"] if name == "sources" else ["content_hash"]
            assert list(detail.clusteringColumns) == want, (
                f"{name} should be clustered by {want} (CLUSTER BY), got {detail.clusteringColumns}")
            assert "deletionVectors" in detail.tableFeatures, (
                f"{name} needs deletion vectors ('delta.enableDeletionVectors' = 'true'), "
                f"features: {detail.tableFeatures}")

        # 1. Scan
        scanned = scan(spark, incoming)
        assert scanned is not None, "scan returned None"
        assert set(scanned.columns) >= {"uri", "content_hash", "media_type", "size", "content"}, (
            f"scan should return uri, content_hash, media_type, size, content; got {scanned.columns}")
        got_types = {r.uri: (r.content_hash, r.media_type) for r in scanned.select("uri", "content_hash", "media_type").collect()}
        assert set(got_types) == set(expected), (
            f"scan found {len(got_types)} files, expected {len(expected)}")
        for uri, (h, mt, _) in expected.items():
            assert got_types[uri] == (h, mt), (
                f"{os.path.relpath(uri[5:], incoming)}: expected {(h[:12], mt)}, got "
                f"{(got_types[uri][0][:12], got_types[uri][1])}")

        # 2. Ingest the media folders in one batch, then the mail one file per commit
        mail = [u for u in expected if "/mail/" in u]
        ingest(spark, scanned.filter(~sf.col("uri").contains("/mail/")), tables, cas_root)
        for uri in mail:
            ingest(spark, scanned.filter(sf.col("uri") == uri), tables, cas_root)
        version = lambda name: spark.sql(f"DESCRIBE HISTORY delta.`{tables[name]}`").first().version  # noqa: E731
        before_rerun = {name: version(name) for name in ["blobs", "sources"]}
        ingest(spark, scanned, tables, cas_root)          # a full rerun must change nothing
        after_rerun = {name: version(name) for name in ["blobs", "sources"]}

        blobs = spark.read.format("delta").load(tables["blobs"])
        rows = {r.content_hash: r for r in blobs.collect()}
        assert set(rows) == hashes, (
            f"blobs should hold one row per distinct content: expected {len(hashes)}, got "
            f"{blobs.count()} rows and {len(rows)} distinct hashes")
        for h, r in rows.items():
            data = next(d for hh, _, d in expected.values() if hh == h)
            if len(data) <= INLINE_LIMIT:
                assert r.content is not None and bytes(r.content) == data and r.blob_uri is None, (
                    f"{h[:12]} ({len(data)} bytes) should be stored inline with blob_uri NULL")
            else:
                assert r.content is None and r.blob_uri, (
                    f"{h[:12]} ({len(data)} bytes) is above the inline limit: content NULL, blob_uri set")
                assert os.path.exists(r.blob_uri) and hashlib.sha256(open(r.blob_uri, "rb").read()).hexdigest() == h, (
                    f"blob_uri {r.blob_uri} should be a file whose SHA-256 is its own name")
        sources = spark.read.format("delta").load(tables["sources"])
        assert sources.count() == len(expected) and sources.select("uri").distinct().count() == len(expected), (
            f"sources should have one row per file ({len(expected)}), got {sources.count()}")
        for name in ["blobs", "sources"]:
            if after_rerun[name] != before_rerun[name]:
                last = spark.sql(f"DESCRIBE HISTORY delta.`{tables[name]}`").first()
                changed = {k: v for k, v in last.operationMetrics.items()
                           if k in ("numTargetRowsInserted", "numTargetRowsUpdated", "numTargetRowsDeleted",
                                    "numOutputRows") and v != "0"}
                assert last.operation == "MERGE" and not changed, (
                    f"Ingesting the same files again must not change {name}; it wrote version "
                    f"{last.version} ({last.operation}, {changed}). Use MERGE, not append")
        print("table versions before/after re-ingesting everything:", before_rerun, after_rerun)

        # 3. Compaction after the one-file-per-commit ingest
        before = spark.sql(f"DESCRIBE DETAIL delta.`{tables['sources']}`").first().numFiles
        compact(spark, tables["sources"])
        after = spark.sql(f"DESCRIBE DETAIL delta.`{tables['sources']}`").first().numFiles
        assert before > 1 and after == 1, f"sources had {before} files; after compaction expected 1, got {after}"
        assert spark.sql(f"DESCRIBE HISTORY delta.`{tables['sources']}`").first().operation == "OPTIMIZE", (
            "compact should run OPTIMIZE")

        # 4. Derived artifacts, idempotent
        derive(spark, tables)
        derive(spark, tables)
        derived = spark.read.format("delta").load(tables["derived"])
        want = {}
        for h, mt, data in expected.values():
            if len(data) > INLINE_LIMIT:
                continue
            if mt == "image/png" and data[12:16] == b"IHDR":
                want[(h, "png_size")] = "%dx%d" % struct.unpack(">II", data[16:24])
            if mt == "audio/wav":
                want[(h, "wav_rate")] = str(struct.unpack("<I", data[24:28])[0])
        got = {(r.content_hash, r.artifact): r.value for r in derived.collect()}
        assert derived.count() == len(want), (
            f"derived should have {len(want)} rows (running derive twice must not duplicate), got {derived.count()}")
        assert got == want, f"derived artifacts differ: {sorted(set(got.items()) ^ set(want.items()))[:4]}"
        assert derived.filter(sf.col("extractor") != EXTRACTOR).count() == 0, "every derived row needs extractor"

        # 5. Forget files
        dup = "file:" + os.path.join(incoming, "large", "red_copy.png")
        assert forget(spark, tables, dup, cas_root) is False, (
            "red_copy.png has the same bytes as images/products/red_16x8.png: forgetting one path "
            "must keep the content and return False")
        red = expected[dup][0]
        assert spark.read.format("delta").load(tables["blobs"]).filter(sf.col("content_hash") == red).count() == 1

        for victim in ["images/products/gradient_32x32.png", "large/scan_a.bin"]:
            uri = "file:" + os.path.join(incoming, victim)
            h, _, data = expected[uri]
            assert forget(spark, tables, uri, cas_root) is True, f"forget({victim}) should remove its content"
            for name in ["sources", "blobs", "derived"]:
                df = spark.read.format("delta").load(tables[name])
                key = "uri" if name == "sources" else "content_hash"
                left = df.filter(sf.col(key) == (uri if name == "sources" else h)).count()
                assert left == 0, f"{victim} still has {left} row(s) in {name}"
            assert not os.path.exists(cas_path(cas_root, h)), f"The CAS copy of {victim} is still on disk"
            needle = data[100:164]
            leaks = [os.path.relpath(f, work) for f in glob.glob(os.path.join(work, "tables", "**", "*.parquet"), recursive=True)
                     if needle in open(f, "rb").read()]
            assert not leaks, (
                f"The bytes of {victim} are still in {leaks}. A DELETE with deletion vectors only "
                "marks rows: purge with REORG TABLE ... APPLY (PURGE), then VACUUM ... RETAIN 0 HOURS")
        ops = [r.operation for r in spark.sql(f"DESCRIBE HISTORY delta.`{tables['blobs']}`").collect()]
        assert "VACUUM END" in ops and "DELETE" in ops, f"blobs history should show DELETE and VACUUM: {ops}"

        print(f"files: {len(expected)}, distinct contents: {len(hashes)}, derived artifacts: {len(want)}")
        print(f"sources files before/after compaction: {before} -> {after}")
        spark.sql(f"DESCRIBE HISTORY delta.`{tables['blobs']}`").select("version", "operation").show(20, truncate=False)
        print("All tests passed!")
    finally:
        spark.stop()
