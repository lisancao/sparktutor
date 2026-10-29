"""
Setup, a First Session and a Tour of the Sample Data - Starter Code

A guided tour of data/messy/: count the files in every folder without
reading them, register the events and logs as temporary views, answer the
same question in SQL and with the DataFrame API, look at a few rows
safely, peek inside the XML, text and binary folders, and read the error
condition of a failed query.
"""

from pyspark.errors import PySparkException
from pyspark.sql import SparkSession, functions as F

ROOT = "data/messy"


def files_per_folder(spark, root):
    """{top-level folder under root: number of files in it, at any depth}.

    Reads only file listings (binaryFile without the content column).
    """
    # TODO 1: read root with format("binaryFile") and recursiveFileLookup,
    #   select the folder name with
    #   F.regexp_extract("path", r"/data/messy/([^/]+)/", 1).alias("folder"),
    #   count rows per folder, collect, and return a dict
    return None


def register_views(spark, root):
    """Create the temporary views `events` and `logs`.

    events: the JSON files in root/events, plus a `file` column with the
            source file name (temp views don't expose _metadata, so add it
            before registering)
    logs:   the text files in root/logs, one row per line, plus `file`
    """
    # TODO 2: read each folder, add F.col("_metadata.file_name") as "file",
    #   and call createOrReplaceTempView("events") / ("logs")
    pass


def lines_per_file_sql(spark):
    """Rows per file of the `logs` view, with SQL: columns file and n, ordered by file."""
    # TODO 3: spark.sql("SELECT ... FROM logs GROUP BY ... ORDER BY ...")
    return None


def lines_per_file_df(spark):
    """The same answer as lines_per_file_sql, with the DataFrame API."""
    # TODO 4: start from spark.table("logs"), then groupBy, agg(F.count("*").alias("n")), orderBy
    return None


def first_rows(df, n):
    """The first n rows of df as a list of Row objects, without collecting everything."""
    # TODO 5: one method call
    return None


def tour_facts(spark, root):
    """A few facts about the sample data, each from a built-in reader.

    xml_orders:  rows in root/xml read with the XML source and rowTag "order"
    doc_files:   files in root/docs, read with the text source, one row per file
    image_files: files under root/images (two subfolders), read with binaryFile
    wav_files:   files in root/audio whose first 4 bytes are the text RIFF
    """
    # TODO 6: four counts:
    #   spark.read.option("rowTag", "order").xml(...)
    #   spark.read.text(..., wholetext=True)
    #   binaryFile with recursiveFileLookup (images/ holds only subfolders)
    #   binaryFile filtered on F.substring("content", 1, 4).cast("string") == "RIFF"
    return None


def error_condition(action):
    """Run action(); return (condition, SQLSTATE) of the Spark error it raises, or None."""
    # TODO 7: call action() inside try; on PySparkException e, return
    #   (e.getCondition(), e.getSqlState()); return None when nothing is raised
    return "not implemented"


# ---- Test harness ----
if __name__ == "__main__":
    import logging
    import os

    spark = (SparkSession.builder
             .appName("TourOfTheData")
             .master("local[4]")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    # PySpark also logs each caught query error as a JSON line; the harness
    # triggers errors on purpose, so quieten those two loggers
    for name in ["DataFrameQueryContextLogger", "SQLQueryContextLogger"]:
        logging.getLogger(name).setLevel(logging.CRITICAL)

    def hidden(name):
        """Spark's listing skips names like these (HadoopFSUtils.shouldFilterOutPathName)."""
        if name.startswith("_metadata") or name.startswith("_common_metadata"):
            return False
        return (name.startswith("_") and "=" not in name) or name.startswith(".") or name.endswith("._COPYING_")

    def python_counts(root):
        counts = {}
        for folder in sorted(os.listdir(root)):
            top = os.path.join(root, folder)
            if not os.path.isdir(top) or hidden(folder):
                continue
            n = 0
            for dirpath, dirnames, filenames in os.walk(top):
                dirnames[:] = [d for d in dirnames if not hidden(d)]
                n += sum(1 for f in filenames if not hidden(f))
            if n:
                counts[folder] = n
        return counts

    try:
        # 1. Files per folder, compared with Python's own walk of the folders
        counts = files_per_folder(spark, ROOT)
        assert counts is not None, "files_per_folder returned None: complete TODO 1"
        counts.pop("", None)  # files directly in data/messy/, if any, have no folder
        expected = python_counts(ROOT)
        assert counts == expected, (
            f"files_per_folder should match the files on disk (hidden names skipped):\n"
            f"  expected {expected}\n  got      {counts}\n"
            "Read with binaryFile and recursiveFileLookup, and take the folder name with "
            "regexp_extract(path, r'/data/messy/([^/]+)/', 1)")
        core = {"audio": 3, "docs": 5, "events": 3, "images": 6, "logs": 2, "mail": 4, "pdf": 2, "xml": 1}
        for folder, n in core.items():
            assert counts.get(folder) == n, f"{folder} should hold {n} files, got {counts.get(folder)}"

        # 2. Temporary views
        register_views(spark, ROOT)
        names = {t.name for t in spark.catalog.listTables()}
        assert {"events", "logs"} <= names, f"Expected temp views events and logs, found {sorted(names)}"
        assert "file" in spark.table("events").columns, "The events view needs a `file` column from _metadata.file_name"
        ev = {r["file"]: r["n"] for r in spark.sql("SELECT file, count(*) AS n FROM events GROUP BY file").collect()}
        assert ev == {"events_2026-10-01.json": 20, "events_2026-10-02.json": 20, "events_2026-10-03.json": 21}, (
            f"events per file should be 20, 20 and 21, got {ev}")

        # 3. SQL and the DataFrame API give the same answer
        sql_rows = lines_per_file_sql(spark)
        df_rows = lines_per_file_df(spark)
        assert sql_rows is not None and df_rows is not None, "complete TODOs 3 and 4"
        assert sql_rows.columns == ["file", "n"] and df_rows.columns == ["file", "n"], (
            f"Both results need the columns file and n; got {sql_rows.columns} and {df_rows.columns}")
        s, d = [tuple(r) for r in sql_rows.collect()], [tuple(r) for r in df_rows.collect()]
        assert s == [("access.log", 200), ("app.log", 134)], f"Expected access.log 200 and app.log 134 lines, got {s}"
        assert s == d, f"The SQL and DataFrame answers differ:\n  SQL {s}\n  DF  {d}"

        # 4. A few rows, safely
        rows = first_rows(spark.table("events"), 3)
        assert isinstance(rows, list) and len(rows) == 3, (
            f"first_rows should return a list of 3 Row objects (take), got {type(rows).__name__}")
        assert all(hasattr(r, "asDict") for r in rows), "first_rows should return Row objects"

        # 5. Peeking into other folders
        facts = tour_facts(spark, ROOT)
        assert facts is not None, "tour_facts returned None: complete TODO 6"
        expected_facts = {"xml_orders": 10, "doc_files": 5, "image_files": 6, "wav_files": 3}
        assert facts == expected_facts, f"tour_facts should be {expected_facts}, got {facts}"

        # 6. Reading errors
        assert error_condition(lambda: spark.read.json(f"{ROOT}/event")) == ("PATH_NOT_FOUND", "42K03"), (
            "A missing folder should give ('PATH_NOT_FOUND', '42K03'): catch PySparkException and return "
            "(e.getCondition(), e.getSqlState())")
        assert error_condition(lambda: spark.table("events").select("evnt")) == (
            "UNRESOLVED_COLUMN.WITH_SUGGESTION", "42703"), "A misspelled column should give UNRESOLVED_COLUMN.WITH_SUGGESTION"
        assert error_condition(lambda: spark.sql("SELECT 1").collect()) is None, "No error should give None"

        print("Files per folder:")
        for folder, n in sorted(counts.items()):
            print(f"  {folder:16} {n}")
        print("Log lines per file (SQL):")
        sql_rows.show()
        print("First event row:", rows[0].asDict())
        print("Tour facts:", facts)
        print("Errors:", error_condition(lambda: spark.read.json(f"{ROOT}/event")),
              error_condition(lambda: spark.table("events").select("evnt")))
        print("All tests passed!")
    finally:
        spark.stop()
