"""
Streaming Readers and Writers - Starter Code

`format("inbox")` is one Python data source with both halves:

- a stream reader over a folder that grows: one row per new file, offsets
  of the form {"v": 1, "mtime_ns": ..., "name": ...}, at most
  maxFilesPerTrigger files per micro-batch, and Trigger.AvailableNow
  support;
- a stream writer that publishes each micro-batch into its own folder
  batch=<id> and skips a batch id it has already published, so a replayed
  batch is not written twice.
"""

import json
import os

from pyspark.sql import SparkSession
from pyspark.sql.datasource import (
    DataSource,
    DataSourceStreamReader,
    DataSourceStreamWriter,
    InputPartition,
    WriterCommitMessage,
)
from pyspark.sql.streaming.datasource import (
    ReadAllAvailable,
    ReadMaxFiles,
    SupportsTriggerAvailableNow,
)

SCHEMA = "name string, kind string, size long, mtime_ns long"
KINDS = {".eml": "email", ".pdf": "pdf", ".md": "text", ".png": "image", ".wav": "audio"}


# ---- Helpers (given) ----
def list_inbox(root):
    """Every visible file as a (mtime_ns, name) key, oldest first.

    The key orders files by modification time, then by name for files
    with the same time. Offsets store the key of the last file read.
    """
    keys = []
    for entry in os.scandir(root):
        if entry.is_file() and not entry.name.startswith((".", "_")):
            keys.append((entry.stat().st_mtime_ns, entry.name))
    return sorted(keys)


def key_of(offset):
    return (offset["mtime_ns"], offset["name"])


def offset_of(key):
    return {"v": 1, "mtime_ns": key[0], "name": key[1]}


class FilePartition(InputPartition):
    def __init__(self, name):
        self.name = name


# ---- The source ----
class InboxDataSource(DataSource):
    @classmethod
    def name(cls):
        return "inbox"

    def schema(self):
        return SCHEMA

    def streamReader(self, schema):
        return InboxStreamReader(self.options)

    def streamWriter(self, schema, overwrite):
        return BatchFolderWriter(self.options)


class InboxStreamReader(DataSourceStreamReader, SupportsTriggerAvailableNow):
    def __init__(self, options):
        self.root = options["path"]
        self.max_files = int(options.get("maxFilesPerTrigger", 2))
        self.target = None   # set by prepareForTriggerAvailableNow

    def initialOffset(self):
        return offset_of((0, ""))

    def getDefaultReadLimit(self):
        return ReadMaxFiles(self.max_files)

    def prepareForTriggerAvailableNow(self):
        # TODO 1: freeze "now". Set self.target to the key of the newest
        #   file in the inbox (the last item of list_inbox(self.root)), or
        #   (0, "") if the inbox is empty.
        pass

    def latestOffset(self, start, limit):
        # TODO 2: plan the next micro-batch.
        #   a. new = the keys from list_inbox(self.root) greater than
        #      key_of(start)
        #   b. if self.target is set, drop keys greater than self.target
        #   c. unless limit is ReadAllAvailable, keep only the first
        #      limit.max_files keys
        #   d. return start if nothing is left, else offset_of(the last key)
        return start

    def partitions(self, start, end):
        # TODO 3: one FilePartition(name) per file whose key k satisfies
        #   key_of(start) < k <= key_of(end).
        return []

    def read(self, partition):
        st = os.stat(os.path.join(self.root, partition.name))
        kind = KINDS.get(os.path.splitext(partition.name)[1].lower(), "other")
        yield (partition.name, kind, st.st_size, st.st_mtime_ns)

    def commit(self, end):
        # Spark has durably processed everything up to `end`. A source that
        # archives or deletes consumed files would do it here.
        pass


# ---- The sink ----
class Staged(WriterCommitMessage):
    def __init__(self, file, rows):
        self.file = file
        self.rows = rows


class BatchFolderWriter(DataSourceStreamWriter):
    def __init__(self, options):
        self.root = options["path"]
        self.staging = os.path.join(self.root, "_staging")

    def write(self, rows):
        """Once per task of a micro-batch, on an executor (given)."""
        import uuid

        os.makedirs(self.staging, exist_ok=True)
        name = f"{uuid.uuid4().hex}.jsonl"
        count = 0
        with open(os.path.join(self.staging, name), "w") as f:
            for row in rows:
                f.write(json.dumps(row.asDict()) + "\n")
                count += 1
        return Staged(name, count)

    def commit(self, messages, batchId):
        """Once per micro-batch, on the driver."""
        target = os.path.join(self.root, f"batch={batchId:05d}")
        summary = os.path.join(target, "_SUMMARY.json")
        # TODO 4: publish the batch, once.
        #   a. If `summary` already exists, this batch id was published
        #      before (a replay): delete the staged files named in the
        #      messages (os.path.join(self.staging, m.file)), append
        #      f"{batchId}\n" to os.path.join(self.root, "_replays.log"),
        #      and return.
        #   b. Otherwise create `target`, move each staged file with rows
        #      into it (os.replace), delete staged files with 0 rows, and
        #      write `summary` as JSON: {"batch": batchId, "rows": total,
        #      "files": [names moved]}.
        pass

    def abort(self, messages, batchId):
        """A task of this micro-batch failed (given)."""
        for m in messages:
            if m is not None:
                path = os.path.join(self.staging, m.file)
                if os.path.exists(path):
                    os.remove(path)


# ---- Test harness ----
if __name__ == "__main__":
    import shutil
    import tempfile

    spark = (SparkSession.builder
        .appName("StreamingSourcesTest")
        .master("local[*]")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    spark.dataSource.register(InboxDataSource)

    base = tempfile.mkdtemp(prefix="inbox_")
    inbox, sink, checkpoint = (os.path.join(base, d) for d in ("inbox", "sink", "checkpoint"))
    os.makedirs(inbox)
    T0 = 1_790_000_000_000_000_000   # a fixed time in nanoseconds, so runs repeat exactly

    def drop(src, name, second):
        """Copy a sample file into the inbox with a known modification time."""
        dst = os.path.join(inbox, name)
        shutil.copy(src, dst)
        t = T0 + second * 1_000_000_000
        os.utime(dst, ns=(t, t))

    def run(trigger):
        query = (spark.readStream.format("inbox")
                 .option("path", inbox)
                 .option("maxFilesPerTrigger", 3)
                 .load()
                 .writeStream.format("inbox")
                 .option("path", sink)
                 .option("checkpointLocation", checkpoint)
                 .trigger(**trigger)
                 .start())
        if "availableNow" in trigger:
            query.awaitTermination()
        else:
            query.processAllAvailable()
            query.stop()
        # progress.numInputRows (an attribute) works in Classic and Connect
        return [(p.batchId, p.numInputRows) for p in query.recentProgress if p.numInputRows]

    def batch_names(batch_id):
        folder = os.path.join(sink, f"batch={batch_id:05d}")
        if not os.path.isdir(folder):
            return []
        names = []
        for f in sorted(os.listdir(folder)):
            if f.endswith(".jsonl"):
                names += [json.loads(line)["name"] for line in open(os.path.join(folder, f))]
        return sorted(names)

    for i in range(4):
        drop(f"data/messy/mail/ticket_{i}.eml", f"ticket_{i}.eml", i)

    # 1. First run, Trigger.AvailableNow: 4 files, at most 3 per batch
    batches = run({"availableNow": True})
    print("run 1 (availableNow):", batches)
    assert batches == [(0, 3), (1, 1)], (
        "with maxFilesPerTrigger=3 and 4 files, expected batches [(0, 3), (1, 1)], got "
        f"{batches}. Check that latestOffset honours limit.max_files and that "
        "prepareForTriggerAvailableNow sets self.target")
    assert batch_names(0) == ["ticket_0.eml", "ticket_1.eml", "ticket_2.eml"], (
        f"batch 0 should hold the three oldest files, got {batch_names(0)}. "
        "Check partitions(start, end) (start < key <= end) and that commit() moves "
        "the staged files into the batch=<id> folder")

    # 2. New files arrive; the restart reads only those
    drop("data/messy/pdf/invoice_1001.pdf", "invoice_1001.pdf", 10)
    for j, doc in enumerate(["returns", "shipping", "privacy"]):
        drop(f"data/messy/docs/{doc}.md", f"{doc}.md", 11 + j)
    batches = run({"processingTime": "0 seconds"})
    print("run 2 (restart, processingTime):", batches)
    assert batches == [(2, 3), (3, 1)], (
        f"the restart should continue at batch 2 and read only the 4 new files, got {batches}")
    assert batch_names(3) == ["privacy.md"], f"batch 3 should be the newest file, got {batch_names(3)}"
    offsets = os.path.join(checkpoint, "offsets", "3")
    print("checkpointed offset of batch 3:", open(offsets).read().splitlines()[-1])

    # 3. Replay the last batch: forget that it was committed, then restart
    os.remove(os.path.join(checkpoint, "commits", "3"))
    crc = os.path.join(checkpoint, "commits", ".3.crc")
    if os.path.exists(crc):
        os.remove(crc)
    batches = run({"availableNow": True})
    print("run 3 (replay):", batches)
    assert batches == [(3, 1)], f"Spark should re-run batch 3 with the same offsets, got {batches}"
    replays = open(os.path.join(sink, "_replays.log")).read().split() \
        if os.path.exists(os.path.join(sink, "_replays.log")) else []
    assert replays == ["3"], (
        "commit() should notice that batch 3 was already published, skip it and log it "
        f"to _replays.log; replays logged: {replays}")

    # 4. Exactly one copy of every file in the sink
    rows = spark.read.json(os.path.join(sink, "batch=*", "*.jsonl"))
    total, distinct = rows.count(), rows.select("name").distinct().count()
    assert (total, distinct) == (8, 8), (
        f"the sink should hold each of the 8 files once, got {total} rows for {distinct} files")
    assert not os.listdir(os.path.join(sink, "_staging")), "no staged files should be left behind"
    rows.groupBy("kind").count().orderBy("kind").show()

    print("All tests passed!")
    spark.stop()
