"""
Packaging, Registration, Testing and Debugging - Solution

The `mailbox` source (one row per .eml file) is the code you would ship
in a package called pyspark_mailbox. Here it lives in the exercise file,
and the work is everything around it:

1. read_without_spark: run the reader as plain Python, with the same
   checks Spark applies, so a unit test needs no SparkSession.
2. error_condition: name the error condition behind a failure, in Classic
   and in Connect.
3. wait_for_worker_logs: read the reader's log lines back with the
   python_worker_logs() table function, which fills in asynchronously.
"""

import re
import time

from pyspark import cloudpickle

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.datasource import DataSource, DataSourceReader, InputPartition
from pyspark.sql.types import StringType, StructField, StructType

SCHEMA = "file string, sender string, subject string, body string"


# ---- The source you would ship in a package (given) ----
class MailPartition(InputPartition):
    def __init__(self, files):
        self.files = files


class MailboxDataSource(DataSource):
    """format("mailbox"): one row per .eml file in the folder given as path."""

    @classmethod
    def name(cls):
        return "mailbox"

    def schema(self):
        return SCHEMA

    def reader(self, schema):
        return MailboxReader(self.options)


class MailboxReader(DataSourceReader):
    def __init__(self, options):
        if "path" not in options:
            raise ValueError("mailbox needs a folder: .load(path)")
        self.root = options["path"]
        self.n = int(options.get("partitions", 2))

    def partitions(self):
        import os

        files = sorted(f for f in os.listdir(self.root) if f.endswith(".eml"))
        return [MailPartition(files[i::self.n]) for i in range(self.n) if files[i::self.n]]

    def read(self, partition):
        import logging
        import os
        from email import policy
        from email.parser import BytesParser

        log = logging.getLogger("mailbox")
        log.setLevel(logging.INFO)
        for name in partition.files:
            with open(os.path.join(self.root, name), "rb") as f:
                msg = BytesParser(policy=policy.default).parse(f)
            if msg["From"] is None:
                raise ValueError(f"{name} has no From header")
            log.info("parsed %s/%s", os.path.basename(self.root), name)
            body = msg.get_body(("plain",)).get_content().strip()
            yield (name, str(msg["From"]), str(msg["Subject"]), body)


# ---- 1. Unit testing without Spark ----
def read_without_spark(source_cls, options, schema):
    """Plan and read like Spark does, in this Python process.

    Returns the list of row tuples. Raises AssertionError for the mistakes
    Spark would reject: partitions() not returning a list of InputPartition,
    a reader that does not pickle, or rows with the wrong number of fields.
    """
    reader = source_cls(dict(options)).reader(schema)
    cloudpickle.dumps(reader)  # Spark ships the reader to executors with cloudpickle
    partitions = reader.partitions()
    assert isinstance(partitions, list), f"partitions() must return a list, got {type(partitions).__name__}"
    assert all(isinstance(p, InputPartition) for p in partitions), \
        "every partition must be an InputPartition"
    rows = []
    for p in partitions:
        cloudpickle.dumps(p)
        for row in reader.read(p):
            assert len(row) == len(schema.fields), \
                f"read() yielded {len(row)} values for {len(schema.fields)} columns: {row}"
            rows.append(tuple(row))
    return rows


# ---- 2. Naming the failure ----
def error_condition(action):
    """Run action(); return None if it succeeds, else its error condition.

    Use e.getCondition() when it gives a name. Some errors have no
    condition attached in Python (a Py4JJavaError in Classic, a
    PythonException in Connect), so fall back to the first [CONDITION]
    written in the message.
    """
    try:
        action()
    except Exception as e:
        get = getattr(e, "getCondition", None)
        name = get() if get else None
        if name:
            return name
        match = re.search(r"\[([A-Z][A-Z0-9_]*(?:\.[A-Z0-9_]+)*)\]", str(e))
        return match.group(1) if match else type(e).__name__
    return None


# ---- 3. Worker logs ----
def wait_for_worker_logs(spark, logger, prefix, expected, timeout=20.0):
    """Poll python_worker_logs() until `expected` messages arrive.

    Counts the messages from `logger` that start with `prefix`. Returns
    them sorted (possibly fewer than expected after the timeout). Logs
    reach the table asynchronously, so a single read right after an
    action can miss some.
    """
    deadline = time.monotonic() + timeout
    while True:
        rows = (spark.tvf.python_worker_logs()
                .filter((F.col("logger") == logger) & F.col("msg").startswith(prefix))
                .select("msg")
                .collect())
        messages = sorted(r.msg for r in rows)
        if len(messages) >= expected or time.monotonic() > deadline:
            return messages
        time.sleep(0.5)


# ---- Test harness ----
if __name__ == "__main__":
    import os
    import shutil
    import tempfile

    MAIL = "data/messy/mail"
    STRUCT = StructType([StructField(n, StringType()) for n in ("file", "sender", "subject", "body")])

    # 1. Unit test first: no SparkSession exists yet
    rows = read_without_spark(MailboxDataSource, {"path": MAIL, "partitions": "3"}, STRUCT)
    assert rows is not None and len(rows) == 4, (
        f"read_without_spark should return 4 rows (one per .eml file), got {rows if rows is None else len(rows)}")
    assert {r[1] for r in rows} == {f"customer{i}@example.com" for i in range(4)}, \
        f"unexpected senders: {sorted(r[1] for r in rows)}"
    print("unit test without Spark:", len(rows), "rows")

    class GeneratorPartitionsReader(MailboxReader):
        def partitions(self):   # a generator, which Spark rejects
            return (p for p in MailboxReader.partitions(self))

    class GeneratorPartitions(MailboxDataSource):
        def reader(self, schema):
            return GeneratorPartitionsReader(self.options)

    try:
        read_without_spark(GeneratorPartitions, {"path": MAIL}, STRUCT)
        caught = False
    except AssertionError:
        caught = True
    assert caught, "read_without_spark should reject a partitions() that does not return a list"

    spark = (SparkSession.builder
        .appName("PackagingTestingTest")
        .master("local[2]")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.pyspark.worker.logging.enabled", "true")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    # 2. Registration
    assert error_condition(lambda: spark.read.format("mailbox").load(MAIL).collect()) \
        == "DATA_SOURCE_NOT_FOUND", "before register(), format('mailbox') should be DATA_SOURCE_NOT_FOUND"
    spark.dataSource.register(MailboxDataSource)
    df = spark.read.format("MailBox").load(MAIL)   # names are case-insensitive
    spark_rows = sorted(tuple(r) for r in df.collect())
    assert spark_rows == sorted(rows), "Spark and read_without_spark should return the same rows"
    print("Spark rows match the unit test")

    class ShadowJson(MailboxDataSource):
        @classmethod
        def name(cls):
            return "json"

    found = error_condition(lambda: spark.dataSource.register(ShadowJson))
    assert found == "DATA_SOURCE_ALREADY_EXISTS", \
        f"registering a source named 'json' should fail with DATA_SOURCE_ALREADY_EXISTS, got {found}"
    print("register('json'):", found)

    class SendersOnlyReader(MailboxReader):
        def read(self, partition):
            for row in MailboxReader.read(self, partition):
                yield row[:2]

    class MailboxV2(MailboxDataSource):
        def schema(self):
            return "file string, sender string"

        def reader(self, schema):
            return SendersOnlyReader(self.options)

    spark.dataSource.register(MailboxV2)   # same name "mailbox": replaces the first one
    assert spark.read.format("mailbox").load(MAIL).columns == ["file", "sender"], \
        "a second register() under the same name should replace the source"
    spark.dataSource.register(MailboxDataSource)
    print("re-register replaced the source")

    # 3. The two error surfaces
    no_path = spark.read.format("mailbox").load()   # no error yet: only schema() ran
    assert error_condition(lambda: no_path.columns) is None, "load() itself should not create the reader"
    found = error_condition(lambda: no_path.collect())
    assert found == "PYTHON_DATA_SOURCE_ERROR", \
        f"a missing path fails when the query is planned, as PYTHON_DATA_SOURCE_ERROR; got {found}"
    print("missing path:", found)
    bad = tempfile.mkdtemp(prefix="mailbox_bad_")
    shutil.copy(os.path.join(MAIL, "ticket_0.eml"), bad)
    with open(os.path.join(bad, "broken.eml"), "w") as f:
        f.write("Subject: no sender\n\nhello\n")
    lazy = spark.read.format("mailbox").load(bad)   # planning succeeds
    found = error_condition(lambda: lazy.collect())
    assert found == "PYTHON_EXCEPTION", f"an error inside read() fails the task as PYTHON_EXCEPTION; got {found}"
    print("error in read():", found)

    # 4. Worker logs, from a folder with a name no earlier read used
    fresh = shutil.copytree(MAIL, os.path.join(tempfile.mkdtemp(), "logcheck"))
    spark.read.format("mailbox").load(fresh).collect()
    messages = wait_for_worker_logs(spark, "mailbox", "parsed logcheck/", expected=4)
    assert messages == [f"parsed logcheck/ticket_{i}.eml" for i in range(4)], (
        f"expected one 'parsed logcheck/ticket_N.eml' line per ticket, found {messages}. "
        "Is spark.sql.pyspark.worker.logging.enabled set, and does wait_for_worker_logs "
        "keep polling until the lines arrive?")
    spark.tvf.python_worker_logs().filter("logger = 'mailbox'") \
        .select("ts", "level", "msg", "context").orderBy("ts").show(truncate=False)

    print("All tests passed!")
    spark.stop()
