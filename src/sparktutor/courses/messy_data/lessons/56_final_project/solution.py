"""
Final Project: Your Own Connector - Solution

`format("casefile")` reads and writes the "case file" format in
data/messy/casefiles: a folder per case with an index (case.json), an
attachments/ folder and a change log (changes.log).

    spark.read.format("casefile").option("table", "cases").load(path)

Tables (option `table`):
    cases        one row per case; loose metadata as VARIANT
    attachments  one row per attachment (listed, on disk, or both), with
                 a checksum check; planned by bytes
    changes      one row per change-log line; also a stream with offsets
                 per file, admission control by bytes and AvailableNow

Other options: `maxPartitionBytes` (default 16384), `pushdown` ("true"
to push filters; needs spark.sql.python.filterPushdown.enabled), `audit`
(a folder: one marker file per case folder a task opens),
`maxBytesPerTrigger` (streaming, default 1024).

Writing: df.write.format("casefile").mode("append" | "overwrite").save(path)
writes one case folder per row, invisible until commit() swaps the
manifest _manifest.json in one os.replace.

The harness at the bottom grades each capability as a separate stage, so
you can work through them in order. Set ONLY to a list of stage names to
run just those while you work.
"""

import datetime
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
import uuid

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.datasource import (
    DataSource,
    DataSourceReader,
    DataSourceStreamReader,
    DataSourceWriter,
    EqualTo,
    GreaterThan,
    GreaterThanOrEqual,
    In,
    InputPartition,
    LessThan,
    LessThanOrEqual,
    WriterCommitMessage,
)
from pyspark.sql.streaming.datasource import ReadAllAvailable, ReadMaxBytes, SupportsTriggerAvailableNow

ONLY = None   # for example ["parsing", "planning"] while you work; None grades every stage

SCHEMAS = {
    "cases": ("case_id string, folder string, schema_version int, opened timestamp, status string, "
              "priority int, tags array<string>, meta variant, attachments int, bytes long, "
              "problems array<string>"),
    "attachments": ("case_id string, folder string, name string, kind string, size long, "
                    "sha256 string, expected_sha256 string, status string"),
    "changes": ("case_id string, line int, ts timestamp, field string, old string, new string, "
                "actor string, raw string, problem string"),
}
MANIFEST = "_manifest.json"
KINDS = {".pdf": "pdf", ".png": "image", ".wav": "audio", ".eml": "email",
         ".txt": "text", ".json": "json"}
CHANGE_LINE = re.compile(r"^(\S+) \| (\w+) \| (.*?) -> (.*?) \| (\S+)$")


def get_log():
    """The connector's logger. Call it where you log: a Logger pickles by name
    only, so a handler added at import time on the driver is not there in a
    worker. The NullHandler keeps warnings off stderr when nothing collects
    them; with worker logging on, python_worker_logs() still gets them."""
    logger = logging.getLogger("casefile")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


def columns_of(table):
    """Column names of a table, from its DDL string (no Spark needed)."""
    return [field.split()[0] for field in SCHEMAS[table].split(", ")]


# =====================================================================
# Stage "parsing": plain functions (no Spark)
# =====================================================================
def parse_ts(text):
    """An ISO 8601 timestamp ('Z' or an offset) as an aware UTC datetime, or None."""
    if not isinstance(text, str):
        return None
    try:
        ts = datetime.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        return None
    return ts.astimezone(datetime.timezone.utc)


def kind_of(name):
    return KINDS.get(os.path.splitext(name)[1].lower(), "other")


def parse_priority(value):
    """'P1'..'P4' or 1..4 -> (int, None); missing -> (None, None); anything else -> (None, 'bad_priority')."""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, "bad_priority"
    if isinstance(value, int) and 1 <= value <= 4:
        return value, None
    if isinstance(value, str) and re.fullmatch(r"[Pp][1-4]", value.strip()):
        return int(value.strip()[1]), None
    return None, "bad_priority"


def parse_tags(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    return [str(t) for t in value]


def parse_index(raw, folder):
    """Normalize the bytes of a case.json (schema 1 or 2) into one dict.

    Keys: case_id, folder, schema_version, opened, status, priority, tags,
    meta (a dict or None), listed (list of {"name", "sha256", "bytes"};
    sha256 and bytes are None for schema 1), problems (sorted list).
    """
    fallback = folder.split("@")[0].upper()
    base = {"case_id": fallback, "folder": folder, "schema_version": None, "opened": None,
            "status": None, "priority": None, "tags": [], "meta": None, "listed": [], "problems": []}
    try:
        doc = json.loads(raw.decode("utf-8-sig"))        # utf-8-sig drops a byte order mark
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {**base, "problems": ["bad_index"]}
    if not isinstance(doc, dict):
        return {**base, "problems": ["bad_index"]}

    problems = []
    if doc.get("schema") == 2:
        version, case_id, opened = 2, doc.get("case_id"), parse_ts(doc.get("opened"))
        status, prio, tags, meta = doc.get("status"), doc.get("priority"), doc.get("tags"), doc.get("meta")
        listed = [{"name": a["name"], "sha256": a.get("sha256"), "bytes": a.get("bytes")}
                  for a in doc.get("attachments") or []]
    elif "schema" not in doc and "id" in doc:
        version, case_id = 1, doc.get("id")
        created = doc.get("created")
        opened = (datetime.datetime.fromtimestamp(created, datetime.timezone.utc)
                  if isinstance(created, (int, float)) and not isinstance(created, bool) else None)
        status, prio, tags, meta = doc.get("state"), doc.get("prio"), doc.get("labels"), doc.get("extra")
        listed = [{"name": n, "sha256": None, "bytes": None} for n in doc.get("attachments") or []]
    else:
        return {**base, "problems": ["bad_index"]}

    priority, problem = parse_priority(prio)
    if problem:
        problems.append(problem)
    case_id = str(case_id).upper() if case_id else fallback
    if case_id != fallback:
        problems.append("id_mismatch")
    return {"case_id": case_id, "folder": folder, "schema_version": version, "opened": opened,
            "status": status.lower() if isinstance(status, str) else None, "priority": priority,
            "tags": parse_tags(tags), "meta": meta if isinstance(meta, dict) else None,
            "listed": listed, "problems": sorted(problems)}


def parse_change_line(line):
    """One changes.log line (without its newline) -> dict, or None if it is not a change."""
    line = line.rstrip("\r")
    m = CHANGE_LINE.match(line.strip())
    if not m:
        return None
    ts = parse_ts(m.group(1))
    if ts is None:
        return None
    return {"ts": ts, "field": m.group(2), "old": m.group(3).strip(), "new": m.group(4).strip(),
            "actor": m.group(5)}


def change_rows(case_id, text, first_line):
    """Rows of the changes table for `text` (whole lines), numbering from first_line.

    Blank lines and comments (#) produce no row; lines that are not changes
    produce a row with raw set and problem 'unparsed'.
    """
    for n, line in enumerate(text.split("\n"), first_line):
        line = line.rstrip("\r").lstrip("\ufeff")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        c = parse_change_line(line)
        if c is None:
            yield (case_id, n, None, None, None, None, None, line, "unparsed")
        else:
            yield (case_id, n, c["ts"], c["field"], c["old"], c["new"], c["actor"], None, None)


def attachment_status(expected_sha, actual_sha, listed, on_disk):
    """'ok', 'sha_mismatch', 'unverified' (no checksum), 'missing' or 'unlisted'."""
    if listed and not on_disk:
        return "missing"
    if on_disk and not listed:
        return "unlisted"
    if expected_sha is None:
        return "unverified"
    return "ok" if expected_sha == actual_sha else "sha_mismatch"


# =====================================================================
# Stage "planning": partitions by bytes
# =====================================================================
def plan_by_bytes(items, target):
    """Group (key, size) items so each group's total is at most target bytes.

    First fit decreasing: largest first (ties by key), each into the first
    group that still has room. An item bigger than target gets a group of
    its own. Items are never split.
    """
    groups, totals = [], []
    for key, size in sorted(items, key=lambda kv: (-kv[1], kv[0])):
        for i, total in enumerate(totals):
            if total + size <= target:
                groups[i].append(key)
                totals[i] += size
                break
        else:
            groups.append([key])
            totals.append(size)
    return groups


def list_case_folders(root):
    """The case folders under root, sorted.

    With a manifest, exactly the folders it lists (so folders of a write
    that never committed stay invisible); without one, every folder that
    has a case.json, skipping names that start with '_' or '.' and job
    folders (name@job) that no manifest has published.
    """
    path = os.path.join(root, MANIFEST)
    if os.path.exists(path):
        with open(path) as f:
            return sorted(json.load(f)["cases"].values())
    return sorted(e.name for e in os.scandir(root)
                  if e.is_dir() and not e.name.startswith(("_", ".")) and "@" not in e.name
                  and os.path.exists(os.path.join(e.path, "case.json")))


def read_index(root, folder):
    with open(os.path.join(root, folder, "case.json"), "rb") as f:
        return parse_index(f.read(), folder)


# =====================================================================
# Stage "batch": the source and its readers
# =====================================================================
class CasePartition(InputPartition):
    def __init__(self, items):
        self.items = items     # case folders, or (folder, name) pairs for attachments


class CaseFileSource(DataSource):
    @classmethod
    def name(cls):
        return "casefile"

    def schema(self):
        table = self.options.get("table", "cases")
        if table not in SCHEMAS:
            raise ValueError(f"casefile: option 'table' must be one of {sorted(SCHEMAS)}, got {table!r}")
        return SCHEMAS[table]

    def reader(self, schema):
        # Two classes on purpose: a reader that defines pushFilters fails every
        # query when spark.sql.python.filterPushdown.enabled is false, and on
        # 4.2.0 pushdown can leak into other scans of a reused DataFrame. So
        # pushdown is opt-in, and the default reader cannot leak.
        if self.options.get("pushdown", "false").lower() == "true":
            return PushdownCaseFileReader(self.options, schema)
        return CaseFileReader(self.options, schema)

    def writer(self, schema, overwrite):
        if self.options.get("table", "cases") != "cases":
            raise ValueError("casefile can only write the cases table")
        return CaseFileWriter(self.options, overwrite)

    def streamReader(self, schema):
        if self.options.get("table", "cases") != "changes":
            raise ValueError("casefile can only stream the changes table (option table=changes)")
        return ChangesStreamReader(self.options)


class CaseFileReader(DataSourceReader):
    def __init__(self, options, schema):
        if "path" not in options:
            raise ValueError("casefile needs a folder: .load(path)")
        self.root = os.path.abspath(options["path"])
        if not os.path.isdir(self.root):
            raise ValueError(f"casefile: {self.root} is not a folder")
        self.table = options.get("table", "cases")
        self.target = int(options.get("maxPartitionBytes", 16384))
        self.audit = options.get("audit")
        # The schema Spark passes (a StructType), or None in tests without Spark
        self.columns = [f.name for f in schema.fields] if schema is not None else columns_of(self.table)
        self.case_ids = None    # set of case ids, or None for all (pushdown)
        self.statuses = None
        self.opened_tests = []  # (operator name, aware datetime)

    # -- planning, on the driver --
    def wanted(self, folder):
        """Does a folder pass the pushed filters? Reads the index only if it must."""
        if self.case_ids is not None and folder.split("@")[0].upper() not in self.case_ids:
            return False
        if self.statuses is None and not self.opened_tests:
            return True
        index = read_index(self.root, folder)
        if self.statuses is not None and index["status"] not in self.statuses:
            return False
        ops = {"GreaterThan": lambda a, b: a > b, "GreaterThanOrEqual": lambda a, b: a >= b,
               "LessThan": lambda a, b: a < b, "LessThanOrEqual": lambda a, b: a <= b}
        return all(index["opened"] is not None and ops[op](index["opened"], value)
                   for op, value in self.opened_tests)

    def partitions(self):
        folders = [f for f in list_case_folders(self.root) if self.wanted(f)]
        if self.table == "attachments":
            items = []
            for folder in folders:
                d = os.path.join(self.root, folder, "attachments")
                names = sorted(os.listdir(d)) if os.path.isdir(d) else []
                items += [((folder, n), os.path.getsize(os.path.join(d, n))) for n in names]
                if not names:
                    items.append(((folder, None), 0))   # a case with nothing on disk still has listed rows
        else:
            name = "case.json" if self.table == "cases" else "changes.log"
            items = [(folder, os.path.getsize(os.path.join(self.root, folder, name))
                      if os.path.exists(os.path.join(self.root, folder, name)) else 0)
                     for folder in folders]
        return [CasePartition(g) for g in plan_by_bytes(items, self.target)]

    # -- reading, on executors --
    def touch(self, folder):
        if self.audit:
            with open(os.path.join(self.audit, f"open-{self.table}-{folder}-{uuid.uuid4().hex}"), "w"):
                pass

    def read(self, partition):
        if not isinstance(partition, CasePartition):
            return
        if self.table == "cases":
            rows = (self.case_row(folder) for folder in partition.items)
        elif self.table == "attachments":
            rows = self.attachment_rows(partition.items)
        else:
            rows = (r for folder in partition.items for r in self.change_rows_of(folder))
        for row in rows:
            yield tuple(row[c] for c in self.columns)

    def case_row(self, folder):
        from pyspark.sql.types import VariantVal

        self.touch(folder)
        index = read_index(self.root, folder)
        d = os.path.join(self.root, folder, "attachments")
        on_disk = sorted(os.listdir(d)) if os.path.isdir(d) else []
        listed = {a["name"] for a in index["listed"]}
        problems = set(index["problems"])
        if listed - set(on_disk):
            problems.add("missing_attachment")
        if set(on_disk) - listed and "bad_index" not in problems:
            problems.add("unlisted_attachment")
        for p in sorted(problems):
            get_log().warning("%s %s", index["case_id"], p)
        return {"case_id": index["case_id"], "folder": folder, "schema_version": index["schema_version"],
                "opened": index["opened"], "status": index["status"], "priority": index["priority"],
                "tags": index["tags"],
                "meta": VariantVal.parseJson(json.dumps(index["meta"])) if index["meta"] is not None else None,
                "attachments": len(index["listed"]),
                "bytes": sum(os.path.getsize(os.path.join(d, n)) for n in on_disk),
                "problems": sorted(problems)}

    def attachment_rows(self, items):
        import hashlib

        by_folder = {}
        for folder, name in items:
            by_folder.setdefault(folder, []).append(name)
        for folder, names in by_folder.items():
            self.touch(folder)
            index = read_index(self.root, folder)
            listed = {a["name"]: a for a in index["listed"]}
            d = os.path.join(self.root, folder, "attachments")
            on_disk = set(os.listdir(d)) if os.path.isdir(d) else set()
            # This partition owns the files it was given; the partition that
            # holds the folder's first planned item also owns the missing ones.
            first = min(on_disk) if on_disk else None
            mine = [n for n in names if n is not None]
            if first is None or first in mine:
                mine += sorted(set(listed) - on_disk)
            for name in sorted(mine):
                exists = name in on_disk
                actual = size = None
                if exists:
                    with open(os.path.join(d, name), "rb") as f:
                        data = f.read()
                    actual, size = hashlib.sha256(data).hexdigest(), len(data)
                expected = listed[name]["sha256"] if name in listed else None
                status = attachment_status(expected, actual, name in listed, exists)
                if status not in ("ok", "unverified"):
                    get_log().warning("%s %s %s", index["case_id"], status, name)
                yield {"case_id": index["case_id"], "folder": folder, "name": name, "kind": kind_of(name),
                       "size": size, "sha256": actual, "expected_sha256": expected, "status": status}

    def change_rows_of(self, folder):
        self.touch(folder)
        path = os.path.join(self.root, folder, "changes.log")
        if not os.path.exists(path):
            return
        with open(path, "rb") as f:
            text = f.read().decode("utf-8")
        case_id = folder.split("@")[0].upper()
        for row in change_rows(case_id, text, 1):
            yield dict(zip(("case_id", "line", "ts", "field", "old", "new", "actor", "raw", "problem"), row))


# =====================================================================
# Stage "pushdown": opt-in, exact, and safe to reuse
# =====================================================================
class PushdownCaseFileReader(CaseFileReader):
    def pushFilters(self, filters):
        for f in filters:
            column = f.attribute if hasattr(f, "attribute") else None
            if column == ("case_id",) and isinstance(f, (EqualTo, In)):
                values = {f.value} if isinstance(f, EqualTo) else set(f.value)
                self.case_ids = values if self.case_ids is None else self.case_ids & values
            elif self.table == "cases" and column == ("status",) and isinstance(f, (EqualTo, In)):
                values = {f.value} if isinstance(f, EqualTo) else set(f.value)
                self.statuses = values if self.statuses is None else self.statuses & values
            elif (self.table == "cases" and column == ("opened",)
                  and isinstance(f, (GreaterThan, GreaterThanOrEqual, LessThan, LessThanOrEqual))):
                self.opened_tests.append((type(f).__name__, f.value))
            else:
                yield f


class CaseFiles:
    """The safe way to use casefile with pushdown on Spark 4.1 to 4.3.

    Every table() call is a fresh load(), so no two scans share a provider
    (see "From Wrong Results to a Fix"). Call it once per reference to a
    table, even inside one query.
    """

    def __init__(self, spark, path, **options):
        self.spark, self.path, self.options = spark, os.path.abspath(path), options

    def table(self, name, **options):
        reader = self.spark.read.format("casefile").option("table", name)
        for k, v in {**self.options, **options}.items():
            reader = reader.option(k, v)
        return reader.load(self.path)


# =====================================================================
# Stage "writer": invisible until one atomic manifest swap
# =====================================================================
def read_manifest(root):
    path = os.path.join(root, MANIFEST)
    if not os.path.exists(path):
        return {"version": 0, "cases": {}, "jobs": []}
    with open(path) as f:
        return json.load(f)


class Written(WriterCommitMessage):
    def __init__(self, folders):
        self.folders = folders    # [(case_id, folder name)]


class CaseFileWriter(DataSourceWriter):
    def __init__(self, options, overwrite):
        if "path" not in options:
            raise ValueError("casefile needs a folder to write to: .save(path)")
        self.root = os.path.abspath(options["path"])
        self.overwrite = overwrite
        self.job = uuid.uuid4().hex[:8]

    def write(self, rows):
        """Each task writes case folders named <case_id>@<job>: invisible until commit.

        A case_id that is not CASE-dddd (any case) raises ValueError("... invalid case_id ...").
        """
        os.makedirs(self.root, exist_ok=True)
        written = []
        for row in rows:
            r = row.asDict()
            case_id = str(r["case_id"]).upper()
            if not re.fullmatch(r"CASE-\d{4}", case_id):
                raise ValueError(f"casefile: invalid case_id {r['case_id']!r}, expected CASE-dddd")
            folder = f"{case_id}@{self.job}"
            d = os.path.join(self.root, folder)
            os.makedirs(os.path.join(d, "attachments"), exist_ok=True)
            opened = r.get("opened")
            meta = r.get("meta")
            index = {"schema": 2, "case_id": case_id,
                     "opened": opened.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                     if opened is not None else None,
                     "status": r.get("status"),
                     "priority": f"P{r['priority']}" if r.get("priority") is not None else None,
                     "tags": list(r.get("tags") or []),
                     "meta": json.loads(meta.toJson()) if meta is not None else None,
                     "attachments": []}
            with open(os.path.join(d, "case.json"), "w") as f:
                json.dump(index, f, indent=2, ensure_ascii=False)
            open(os.path.join(d, "changes.log"), "w").close()
            written.append((case_id, folder))
        return Written(written)

    def commit(self, messages):
        written = [w for m in messages for w in m.folders]
        ids = [case_id for case_id, _ in written]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"casefile: duplicate case_id in this write: {dupes}")
        old = read_manifest(self.root)
        if not old["cases"] and not os.path.exists(os.path.join(self.root, MANIFEST)):
            # First write into a folder that may hold a plain export: adopt it.
            old["cases"] = {} if self.overwrite else {
                f.split("@")[0].upper(): f for f in list_case_folders(self.root)}
        clash = sorted(set(ids) & set(old["cases"])) if not self.overwrite else []
        if clash:
            raise ValueError(f"casefile: case_id already exists (use overwrite): {clash}")
        cases = {} if self.overwrite else dict(old["cases"])
        cases.update(dict(written))
        new = {"version": old["version"] + 1, "cases": cases,
               "jobs": old["jobs"] + [{"job": self.job, "mode": "overwrite" if self.overwrite else "append",
                                       "cases": len(written)}]}
        tmp = os.path.join(self.root, f".{MANIFEST}.{self.job}")
        with open(tmp, "w") as f:
            json.dump(new, f, indent=1)
        os.replace(tmp, os.path.join(self.root, MANIFEST))      # the commit point
        # Only now delete folders the new manifest no longer points to.
        for folder in set(old["cases"].values()) - set(cases.values()):
            shutil.rmtree(os.path.join(self.root, folder), ignore_errors=True)

    def abort(self, messages):
        for entry in os.listdir(self.root) if os.path.isdir(self.root) else []:
            if entry.endswith("@" + self.job):
                shutil.rmtree(os.path.join(self.root, entry), ignore_errors=True)


# =====================================================================
# Stage "streaming": the changes table as a stream
# =====================================================================
class ChangesRange(InputPartition):
    def __init__(self, folder, start, end, first_line):
        self.folder, self.start, self.end, self.first_line = folder, start, end, first_line


def complete_lines(path, start):
    """[(end byte, newline count)] for each complete line after byte `start`."""
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read()
    out, pos = [], start
    for piece in data.split(b"\n")[:-1]:          # the last piece has no newline yet
        pos += len(piece) + 1
        out.append(pos)
    return out


class ChangesStreamReader(DataSourceStreamReader, SupportsTriggerAvailableNow):
    """Offsets: {"v": 1, "pos": {folder: [byte, lines]}}, bytes and lines consumed per log."""

    def __init__(self, options):
        self.root = os.path.abspath(options["path"])
        self.max_bytes = int(options.get("maxBytesPerTrigger", 1024))
        self.target = None

    def initialOffset(self):
        return {"v": 1, "pos": {}}

    def getDefaultReadLimit(self):
        return ReadMaxBytes(self.max_bytes)

    def pending(self, start):
        """{folder: [end byte of each complete unread line]}, in folder order."""
        out = {}
        for folder in list_case_folders(self.root):
            path = os.path.join(self.root, folder, "changes.log")
            if not os.path.exists(path):
                continue
            begin = start["pos"].get(folder, [0, 0])[0]
            ends = complete_lines(path, begin)
            if self.target is not None:
                cap = self.target.get(folder, 0)
                ends = [e for e in ends if e <= cap]
            if ends:
                out[folder] = ends
        return out

    def prepareForTriggerAvailableNow(self):
        everything = self.pending({"v": 1, "pos": {}})
        self.target = {folder: ends[-1] for folder, ends in everything.items()}

    def latestOffset(self, start, limit):
        budget = None if isinstance(limit, ReadAllAvailable) else getattr(limit, "max_bytes", None)
        pos = {k: list(v) for k, v in start["pos"].items()}
        used, took = 0, False
        for folder, ends in self.pending(start).items():
            begin, lines = pos.get(folder, [0, 0])
            for end in ends:
                size = end - begin
                if budget is not None and took and used + size > budget:
                    return {"v": 1, "pos": pos}
                used += size
                took = True
                begin, lines = end, lines + 1
                pos[folder] = [begin, lines]
        return {"v": 1, "pos": pos}

    def partitions(self, start, end):
        parts = []
        for folder, (stop, _) in sorted(end["pos"].items()):
            begin, lines = start["pos"].get(folder, [0, 0])
            if stop > begin:
                parts.append(ChangesRange(folder, begin, stop, lines + 1))
        return parts

    def read(self, partition):
        with open(os.path.join(self.root, partition.folder, "changes.log"), "rb") as f:
            f.seek(partition.start)
            text = f.read(partition.end - partition.start).decode("utf-8")
        text = text[:-1] if text.endswith("\n") else text      # the range ends with a newline
        yield from change_rows(partition.folder.split("@")[0].upper(), text, partition.first_line)

    def commit(self, end):
        pass


# =====================================================================
# Stage "offline_tests": tests that need no Spark
# =====================================================================
SAMPLE = "data/messy/casefiles"


class OfflineTests(unittest.TestCase):
    """Run without a SparkSession. The harness also runs them against
    broken versions of your functions; each broken version must fail at
    least one test."""

    def test_v2_index(self):
        with open(os.path.join(SAMPLE, "CASE-0001", "case.json"), "rb") as f:
            i = parse_index(f.read(), "CASE-0001")
        self.assertEqual((i["case_id"], i["schema_version"], i["status"], i["priority"]), ("CASE-0001", 2, "open", 2))
        self.assertEqual(i["opened"], datetime.datetime(2026, 3, 2, 9, 15, tzinfo=datetime.timezone.utc))
        self.assertEqual(i["problems"], [])

    def test_v1_index(self):
        raw = b'{"id": "case-7", "created": 0, "state": "OPEN", "prio": 2, "labels": "a, b", "attachments": ["x.png"]}'
        i = parse_index(raw, "CASE-7")
        self.assertEqual((i["case_id"], i["schema_version"], i["status"], i["priority"], i["tags"]),
                         ("CASE-7", 1, "open", 2, ["a", "b"]))
        self.assertEqual(i["listed"], [{"name": "x.png", "sha256": None, "bytes": None}])

    def test_bom_and_offset(self):
        raw = "\ufeff".encode() + b'{"schema": 2, "case_id": "C-9", "opened": "2026-03-21T10:30:00+02:00"}'
        i = parse_index(raw, "c-9")
        self.assertEqual(i["problems"], [])
        self.assertEqual(i["opened"], datetime.datetime(2026, 3, 21, 8, 30, tzinfo=datetime.timezone.utc))

    def test_bad_index_and_priority(self):
        self.assertEqual(parse_index(b'{"schema": 2, "case', "CASE-8")["problems"], ["bad_index"])
        self.assertEqual(parse_index(b'{"schema": 2, "case_id": "X", "priority": "urgent"}', "X")["problems"],
                         ["bad_priority"])

    def test_change_lines(self):
        c = parse_change_line("2026-03-21T09:00:00Z | status | new -> open | dev\r")
        self.assertEqual((c["field"], c["old"], c["new"], c["actor"]), ("status", "new", "open", "dev"))
        self.assertIsNone(parse_change_line("2026-03-25T09:30:00Z | status | open triage | dev"))
        self.assertIsNone(parse_change_line("status changed by ana"))
        rows = list(change_rows("C", "# header\n\n2026-03-21T09:00:00Z | status | a -> b | x\nnonsense", 1))
        self.assertEqual([(r[1], r[8]) for r in rows], [(3, None), (4, "unparsed")])

    def test_attachment_status(self):
        self.assertEqual(attachment_status("a", "a", True, True), "ok")
        self.assertEqual(attachment_status("a", "b", True, True), "sha_mismatch")
        self.assertEqual(attachment_status(None, "b", True, True), "unverified")
        self.assertEqual(attachment_status("a", None, True, False), "missing")
        self.assertEqual(attachment_status(None, "b", False, True), "unlisted")

    def test_plan_by_bytes(self):
        groups = plan_by_bytes([("a", 50), ("b", 30), ("c", 30), ("d", 20), ("big", 500)], 60)
        self.assertEqual(groups, [["big"], ["a"], ["b", "c"], ["d"]])
        sizes = {"a": 50, "b": 30, "c": 30, "d": 20, "big": 500}
        for g in groups:
            self.assertTrue(len(g) == 1 or sum(sizes[k] for k in g) <= 60)
        self.assertEqual(plan_by_bytes([], 10), [])

    def test_reader_without_spark(self):
        from pyspark import cloudpickle

        reader = CaseFileReader({"path": SAMPLE, "table": "attachments", "maxPartitionBytes": "16384"}, None)
        parts = reader.partitions()
        cloudpickle.loads(cloudpickle.dumps((reader, parts)))
        rows = [r for p in parts for r in reader.read(p)]
        status = {(r[0], r[2]): r[7] for r in rows}
        self.assertEqual(status[("CASE-0004", "scan.png")], "missing")
        self.assertEqual(status[("CASE-0006", "receipt.pdf")], "sha_mismatch")
        self.assertEqual(status[("CASE-0005", "stray.tmp")], "unlisted")


# =====================================================================
# Stage "design_review"
# =====================================================================
DESIGN_REVIEW = """
## Decisions

- One source, three tables chosen with the `table` option, because the
  three grains (case, attachment, change line) cannot share one schema
  without a lot of NULLs, and a consumer usually needs one of them.
- Partitions are planned by bytes with first fit decreasing over files
  (attachments) or index and log sizes (cases, changes), so the large
  recording does not share a task with everything else.
- Loose case metadata is VARIANT: its keys differ per case and per
  schema version, and VARIANT keeps it queryable without a schema.
- Stream offsets are byte positions per change log, plus a line count
  for line numbers; only complete lines (ending in a newline) are read.
- A write publishes by replacing one manifest file; data folders are
  named per job and never renamed over live data.

## Trade-offs

- Pushdown on status and opened reads every index on the driver during
  planning, then again on the executor. For thousands of cases a small
  catalog file would be cheaper than opening each case.json twice.
- Pushdown is opt-in. It saves I/O but needs the internal flag, and on
  Spark 4.1 to 4.3 a reused DataFrame can leak pushed filters, so the
  default reader has no pushFilters and CaseFiles loads afresh per table.
- The manifest makes writes atomic for readers of this connector only;
  a tool that lists folders directly sees uncommitted job folders.

## Failure modes

- A task fails during write: abort() deletes the folders of this job;
  the manifest is untouched, so readers never see a partial write.
- Two rows with one case_id, or an append of an existing case: commit()
  raises before the manifest changes, and Spark then calls abort().
- The driver dies between os.replace of the manifest and the cleanup of
  replaced folders: the data is correct; old folders are left behind as
  garbage that a later overwrite or a vacuum must remove.
- A change log is appended while a batch runs: offsets only cover
  complete lines that existed when latestOffset ran, so a half-written
  line waits for the next batch.
- A change log is rewritten instead of appended: byte offsets become
  wrong. The format must be append-only; detecting a shrink (size below
  the offset) and failing would be the next improvement.
- A corrupt or truncated index: the case still appears, with NULL
  fields and the problem bad_index, instead of failing the query.

## Testing

- Plain unittest tests for every parser and the planner, run without
  Spark, and checked by the harness against broken versions.
- Integration tests in a local session: plans, audit files to prove
  skipped folders, the writer under injected failures, and the stream
  compared with the batch reader of the same folder.

## What I would change for production

- A catalog file of index summaries so planning does not open every
  case.json; a vacuum command for folders no manifest points to.
- Out-of-order change lines are kept as they are; ordering by ts is the
  consumer's job, and flagging them in a stream needs state per log.
- Package it as pyspark_casefile with DefaultSource and the unit tests.
"""


# =====================================================================
# The harness (given): every stage is graded on its own
# =====================================================================
DATA = os.path.abspath("data/messy/casefiles")
EXPECTED_PROBLEMS = {
    "CASE-0004": ["missing_attachment"], "CASE-0005": ["unlisted_attachment"],
    "CASE-0006": [], "CASE-0008": ["bad_index"], "CASE-0010": ["bad_priority"],
}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def stage_parsing(ctx):
    with open(os.path.join(DATA, "CASE-0007", "case.json"), "rb") as f:
        v1 = parse_index(f.read(), "CASE-0007")
    check(v1["schema_version"] == 1 and v1["case_id"] == "CASE-0007", f"CASE-0007 is a version 1 index, got {v1}")
    check(v1["opened"] == datetime.datetime(2026, 3, 4, 9, 30, tzinfo=datetime.timezone.utc),
          f"version 1 'created' is epoch seconds (1772616600 = 2026-03-04 09:30 UTC), got {v1['opened']}")
    check((v1["status"], v1["priority"], v1["tags"]) == ("open", 2, ["billing", "vip"]),
          f"v1 state/prio/labels should become ('open', 2, ['billing', 'vip']), got "
          f"{(v1['status'], v1['priority'], v1['tags'])}")
    check(v1["meta"] == {"imported_from": "legacy-crm", "legacy_id": 7731}, "v1 'extra' is the metadata")
    with open(os.path.join(DATA, "case-0009", "case.json"), "rb") as f:
        v9 = parse_index(f.read(), "case-0009")
    check(v9["problems"] == [] and v9["case_id"] == "CASE-0009",
          f"case-0009 starts with a byte order mark; decode with utf-8-sig. Got problems {v9['problems']}")
    check(v9["opened"] == datetime.datetime(2026, 3, 21, 8, 30, tzinfo=datetime.timezone.utc),
          f"2026-03-21T10:30:00+02:00 is 08:30 UTC, got {v9['opened']}")
    with open(os.path.join(DATA, "CASE-0008", "case.json"), "rb") as f:
        v8 = parse_index(f.read(), "CASE-0008")
    check(v8["problems"] == ["bad_index"] and v8["case_id"] == "CASE-0008",
          f"a truncated index gives case_id from the folder and problems ['bad_index'], got {v8}")
    with open(os.path.join(DATA, "CASE-0010", "case.json"), "rb") as f:
        v10 = parse_index(f.read(), "CASE-0010")
    check(v10["priority"] is None and v10["problems"] == ["bad_priority"],
          f"priority 'urgent' is not P1 to P4: priority None, problems ['bad_priority']; got {v10}")
    c = parse_change_line("2026-03-21T09:00:00Z | status | new -> open | dev\r")
    check(c is not None and (c["old"], c["new"], c["actor"]) == ("new", "open", "dev"),
          f"a CRLF change line should parse without the \\r, got {c}")
    check(parse_change_line("2026-03-25T09:30:00Z | status | open triage | dev") is None,
          "a line without '->' is not a change")
    check([attachment_status("a", "a", True, True), attachment_status("a", "b", True, True),
           attachment_status(None, "b", True, True), attachment_status("a", None, True, False),
           attachment_status(None, "b", False, True)] == ["ok", "sha_mismatch", "unverified", "missing", "unlisted"],
          "attachment_status should give ok, sha_mismatch, unverified, missing, unlisted for the five cases")
    return "v1 and v2 indexes, BOM, offsets, bad index, priorities, change lines, statuses"


def stage_planning(ctx):
    items = [("a", 50), ("b", 30), ("c", 30), ("d", 20), ("big", 500)]
    got = plan_by_bytes(items, 60)
    check(got == [["big"], ["a"], ["b", "c"], ["d"]],
          f"plan_by_bytes({items}, 60) should be [['big'], ['a'], ['b', 'c'], ['d']] (first fit decreasing), got {got}")
    check(plan_by_bytes([], 10) == [], "no items, no groups")
    folders = list_case_folders(DATA)
    check(folders == ["CASE-0001", "CASE-0002", "CASE-0003", "CASE-0004", "CASE-0005", "CASE-0006",
                      "CASE-0007", "CASE-0008", "CASE-0010", "case-0009"],
          f"list_case_folders should find the 10 case folders and skip README.txt, .DS_Store and _staging; got {folders}")
    reader = CaseFileReader({"path": DATA, "table": "attachments"}, None)
    parts = reader.partitions()
    sizes = {(f, n): os.path.getsize(os.path.join(DATA, f, "attachments", n))
             for p in parts for f, n in p.items if n is not None}
    for p in parts:
        total = sum(sizes.get(i, 0) for i in p.items)
        check(len(p.items) == 1 or total <= 16384,
              f"a partition holds {total} bytes (> maxPartitionBytes 16384) in {len(p.items)} files")
    big = [p for p in parts if ("CASE-0002", "call.wav") in p.items]
    check(len(big) == 1 and len(big[0].items) == 1, "the 40 KB call.wav should have a partition of its own")
    check(len(parts) == 2, f"with the default 16384 bytes the attachments plan into 2 partitions, got {len(parts)}")
    return f"{len(parts)} attachment partitions, call.wav alone"


def stage_batch(ctx):
    spark = ctx["spark"]
    cases = spark.read.format("casefile").option("table", "cases").load(DATA)
    check(cases.columns == columns_of("cases"), f"cases columns should follow SCHEMAS['cases'], got {cases.columns}")
    rows = {r["case_id"]: r for r in cases.collect()}
    check(len(rows) == 10, f"10 cases expected, got {sorted(rows)}")
    for case_id, problems in EXPECTED_PROBLEMS.items():
        check(rows[case_id]["problems"] == problems, f"{case_id} problems should be {problems}, got {rows[case_id]['problems']}")
    check(rows["CASE-0002"]["bytes"] == 40124, f"CASE-0002 holds 40124 bytes of attachments, got {rows['CASE-0002']['bytes']}")
    check(rows["CASE-0004"]["attachments"] == 2, "CASE-0004 lists 2 attachments (one is missing)")
    att = spark.read.format("casefile").option("table", "attachments").load(DATA)
    by_status = {r["status"]: r["n"] for r in att.groupBy("status").agg(F.count("*").alias("n")).collect()}
    check(by_status == {"ok": 10, "missing": 1, "unlisted": 2, "sha_mismatch": 1, "unverified": 1},
          f"attachment statuses should be ok 10, missing 1, unlisted 2 (stray.tmp and CASE-0008's note), "
          f"sha_mismatch 1, unverified 1 (the v1 case); got {by_status}")
    check(att.select(F.spark_partition_id()).distinct().count() == 2, "attachments should read in 2 partitions")
    ch = spark.read.format("casefile").option("table", "changes").load(DATA)
    n = ch.count()
    bad = sorted((r["case_id"], r["line"]) for r in ch.filter("problem = 'unparsed'").collect())
    check(n == 44, f"the change logs hold 44 change lines (comments and blank lines are not rows), got {n}")
    check(bad == [("CASE-0004", 6), ("CASE-0010", 4)], f"unparsed lines should be CASE-0004 line 6 and CASE-0010 line 4, got {bad}")
    first9 = ch.filter("case_id = 'CASE-0009'").orderBy("line").first()
    check(first9["field"] == "status" and first9["line"] == 1, "case-0009's first line (after the BOM) is a status change")
    return "10 cases, 15 attachment rows, 44 changes"


def stage_variant(ctx):
    spark = ctx["spark"]
    cases = spark.read.format("casefile").option("table", "cases").load(DATA)
    check(dict(cases.dtypes)["meta"] == "variant", f"meta should be VARIANT, got {dict(cases.dtypes)['meta']}")
    got = {r["case_id"]: (r["tier"], r["sla"]) for r in cases.select(
        "case_id", F.expr("variant_get(meta, '$.customer.tier', 'string')").alias("tier"),
        F.expr("try_variant_get(meta, '$.sla_hours', 'int')").alias("sla")).collect()}
    check(got["CASE-0001"] == ("gold", 24) and got["CASE-0010"] == ("gold", 4) and got["CASE-0002"] == (None, None),
          f"variant_get on meta: CASE-0001 ('gold', 24), CASE-0010 ('gold', 4), CASE-0002 (None, None); got "
          f"{got.get('CASE-0001'), got.get('CASE-0010'), got.get('CASE-0002')}")
    name = cases.filter("case_id = 'CASE-0009'").select(
        F.expr("variant_get(meta, '$.customer.name', 'string')")).first()[0]
    check(name == "Hélène Côté", f"non-ASCII metadata should survive: got {name!r}")
    legacy = cases.filter("case_id = 'CASE-0007'").select(F.expr("variant_get(meta, '$.legacy_id', 'int')")).first()[0]
    check(legacy == 7731, "the v1 case's 'extra' object is its meta")
    return "meta is VARIANT and queryable"


def plan_text(df):
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        df.explain("formatted")
    return buf.getvalue()


def audited(spark, table, condition, **options):
    audit = tempfile.mkdtemp(prefix="audit_")
    df = CaseFiles(spark, DATA, pushdown="true", audit=audit, **options).table(table).filter(condition)
    rows = df.collect()
    opened = sorted({name.split("-", 2)[2].rsplit("-", 1)[0] for name in os.listdir(audit)})
    return df, rows, opened


def stage_pushdown(ctx):
    spark = ctx["spark"]
    flag = "spark.sql.python.filterPushdown.enabled"
    spark.conf.set(flag, "false")
    try:
        n = spark.read.format("casefile").option("table", "cases").load(DATA).filter("status = 'open'").count()
    except Exception as e:  # noqa: BLE001
        raise AssertionError("with the flag off and no pushdown option the default reader must work; it failed: "
                             + explain_error(e)) from None
    finally:
        spark.conf.set(flag, "true")
    check(n == 5, f"5 cases are open, got {n}")

    df, rows, opened = audited(spark, "cases", "status = 'open'")
    check(len(rows) == 5, f"status = 'open' should give 5 cases with pushdown, got {len(rows)}")
    plan = plan_text(df)
    check("PushedFilters: [EqualTo(status,open)" in plan, "the plan should list EqualTo(status,open) under PushedFilters")
    check(opened == ["CASE-0001", "CASE-0005", "CASE-0007", "CASE-0010", "case-0009"],
          f"tasks should open only the folders of the 5 open cases, got {opened}")

    window = "opened >= timestamp'2026-03-10 00:00:00' AND opened < timestamp'2026-03-22 00:00:00'"
    df, rows, opened = audited(spark, "cases", window)
    check(sorted(r["case_id"] for r in rows) == ["CASE-0005", "CASE-0006", "CASE-0009"],
          f"cases opened from 2026-03-10 to before 2026-03-22 (UTC): CASE-0005, CASE-0006, CASE-0009; got "
          f"{sorted(r['case_id'] for r in rows)}")
    check(opened == ["CASE-0005", "CASE-0006", "case-0009"], f"only those folders should be opened, got {opened}")

    df, rows, opened = audited(spark, "attachments", "case_id IN ('CASE-0002', 'CASE-0004')")
    check(len(rows) == 4 and opened == ["CASE-0002", "CASE-0004"],
          f"attachments of CASE-0002 and CASE-0004: 4 rows from 2 folders; got {len(rows)} rows from {opened}")
    _, rows, opened = audited(spark, "changes", "case_id = 'CASE-0003' AND field = 'status'")
    check(len(rows) == 3 and opened == ["CASE-0003"], f"CASE-0003 has 3 status changes; got {len(rows)} from {opened}")

    # The 4.2.0 leak: the default reader is safe on a reused DataFrame...
    plain = spark.read.format("casefile").option("table", "cases").load(DATA)
    seq = [plain.count(), plain.filter("status = 'open'").count(), plain.count()]
    check(seq == [10, 5, 10], f"the default reader must not leak on a reused DataFrame: {seq}")
    # ...and CaseFiles gives fresh loads with pushdown on
    cf = CaseFiles(spark, DATA, pushdown="true")
    check(cf.table("cases").filter("status = 'open'").count() == 5 and cf.table("cases").count() == 10,
          "CaseFiles.table() should load afresh each time")
    joined = cf.table("cases").alias("c").join(cf.table("attachments").alias("a"), "case_id") \
        .filter("c.status = 'open'").count()
    check(joined == 7, f"open cases joined with their attachment rows: expected 7, got {joined}")
    return "flag off works, pushed filters skip folders, no leak through CaseFiles"


def stage_writer(ctx):
    spark = ctx["spark"]
    out = os.path.join(tempfile.mkdtemp(prefix="cases_out_"), "export")
    source = spark.read.format("casefile").option("table", "cases").load(DATA)
    cols = ["case_id", "status", "priority", "opened", "tags", "meta"]

    def visible():
        return sorted(r["case_id"] for r in spark.read.format("casefile").option("table", "cases").load(out).collect())

    def try_save(df, mode, label):
        try:
            df.write.format("casefile").mode(mode).save(out)
        except Exception as e:  # noqa: BLE001
            return str(e)
        if label:
            raise AssertionError(f"{label} should have failed")
        return None

    err = try_save(source.filter("case_id <= 'CASE-0005'").select(*cols), "append", None)
    check(err is None, f"the first append failed: {err and explain_error(Exception(err))}")
    check(visible() == ["CASE-0001", "CASE-0002", "CASE-0003", "CASE-0004", "CASE-0005"], f"after append: {visible()}")
    m = read_manifest(out)
    check(m["version"] == 1 and len(m["cases"]) == 5, f"the manifest should list 5 cases at version 1, got {m}")

    before = (json.dumps(read_manifest(out), sort_keys=True), sorted(os.listdir(out)))
    # One write task, in case_id order: it writes four case folders, then write()
    # must reject the invalid case_id. (A failure injected with raise_error does
    # not test abort(): the JVM feeds rows to Python from its own thread, and in
    # testing the task always failed before write() had written anything.)
    broken = (source.filter("case_id > 'CASE-0005'").select(*cols)
              .withColumn("case_id", F.when(F.col("case_id") == "CASE-0010", F.lit("not a case"))
                          .otherwise(F.col("case_id")))
              .orderBy("case_id").coalesce(1))
    err = try_save(broken, "append", "a write with an invalid case_id")
    check("invalid case_id" in err, "write() should reject case_id 'not a case' with a message containing "
          "'invalid case_id', got: " + explain_error(Exception(err)))
    after = (json.dumps(read_manifest(out), sort_keys=True), sorted(os.listdir(out)))
    check(before == after, "a failed write must leave the manifest and the folder exactly as they were "
          f"(abort() should delete this job's folders); new entries: {sorted(set(after[1]) - set(before[1]))}")

    dup = source.filter("case_id = 'CASE-0006'").select(*cols)
    err = try_save(dup.union(dup).repartition(2), "append", "a write with a duplicate case_id")
    check("duplicate" in err, "a duplicate case_id should fail in commit() with a message about duplicates, got: "
          + explain_error(Exception(err)))
    clash = try_save(source.filter("case_id = 'CASE-0001'").select(*cols), "append", "appending an existing case")
    check("exists" in clash, "appending an existing case_id should fail in commit() with 'already exists', got: "
          + explain_error(Exception(clash)))
    check((json.dumps(read_manifest(out), sort_keys=True), sorted(os.listdir(out))) == before,
          "rejected commits must not change anything")

    err = try_save(source.filter("case_id > 'CASE-0005'").select(*cols), "overwrite", None)
    check(err is None, f"overwrite failed: {err and explain_error(Exception(err))}")
    check(visible() == ["CASE-0006", "CASE-0007", "CASE-0008", "CASE-0009", "CASE-0010"], f"after overwrite: {visible()}")
    check(len([e for e in os.listdir(out) if not e.startswith((".", "_"))]) == 5,
          "overwrite should delete the replaced folders after the manifest swap")
    back = spark.read.format("casefile").option("table", "cases").load(out)
    a = {tuple(r) for r in back.select("case_id", "status", "priority", "opened", F.to_json("meta")).collect()}
    b = {tuple(r) for r in source.filter("case_id > 'CASE-0005'")
         .select("case_id", "status", "priority", "opened", F.to_json("meta")).collect()}
    check(a == b, f"a round trip should keep case_id, status, priority, opened and meta: {sorted(a ^ b)[:3]}")
    return "append, failed task, duplicate, clash, overwrite, round trip"


def stage_streaming(ctx):
    spark = ctx["spark"]
    base = tempfile.mkdtemp(prefix="stream_")
    live, sink, ckpt = (os.path.join(base, d) for d in ("live", "sink", "ckpt"))
    shutil.copytree(DATA, live)

    def run(trigger):
        q = (spark.readStream.format("casefile").option("table", "changes")
             .option("maxBytesPerTrigger", 400).load(live)
             .writeStream.format("parquet").option("path", sink).option("checkpointLocation", ckpt)
             .trigger(**trigger).start())
        if "availableNow" in trigger:
            q.awaitTermination()
        else:
            q.processAllAvailable()
            q.stop()
        return [(p.batchId, p.numInputRows) for p in q.recentProgress if p.numInputRows]

    def offsets(batch):
        with open(os.path.join(ckpt, "offsets", str(batch))) as f:
            return json.loads(f.read().splitlines()[-1])

    def consumed(a, b):
        return sum(b["pos"][k][0] - a["pos"].get(k, [0, 0])[0] for k in b["pos"])

    first = run({"availableNow": True})
    check(len(first) >= 5, f"with maxBytesPerTrigger 400 the first run should take several batches, got {first}")
    prev = {"v": 1, "pos": {}}
    for batch, _ in first:
        cur = offsets(batch)
        check(set(cur) == {"v", "pos"}, f"offsets should look like {{'v': 1, 'pos': {{folder: [byte, lines]}}}}, got {cur}")
        used = consumed(prev, cur)
        check(used <= 400, f"batch {batch} consumed {used} bytes of change logs; maxBytesPerTrigger is 400")
        prev = cur
    check(prev["pos"]["CASE-0003"][1] == 3, "CASE-0003's last line has no newline yet: only 3 lines may be consumed")

    with open(os.path.join(live, "CASE-0003", "changes.log"), "ab") as f:
        f.write(b"\n2026-03-05T10:00:00Z | status | triage -> open | ana\n2026-03-05T10:05:00Z | priority | P1")
    os.makedirs(os.path.join(live, "CASE-0011", "attachments"))
    with open(os.path.join(live, "CASE-0011", "case.json"), "w") as f:
        json.dump({"schema": 2, "case_id": "CASE-0011", "opened": "2026-03-27T08:00:00Z", "status": "new"}, f)
    with open(os.path.join(live, "CASE-0011", "changes.log"), "w") as f:
        f.write("2026-03-27T08:00:00Z | status | new -> open | binh\n2026-03-27T08:10:00Z | status | open -> waiting | binh\n")
    second = run({"processingTime": "0 seconds"})
    check(second and second[0][0] == first[-1][0] + 1, f"the restart should continue after batch {first[-1][0]}, got {second}")
    check(sum(n for _, n in second) == 4, f"the restart should read exactly the 4 new complete lines, got {second}")

    with open(os.path.join(live, "CASE-0003", "changes.log"), "ab") as f:
        f.write(b" -> P2 | ana\n")
    third = run({"availableNow": True})
    check(sum(n for _, n in third) == 1, f"completing the partial line should give exactly 1 row, got {third}")

    streamed = spark.read.parquet(sink)
    batch = spark.read.format("casefile").option("table", "changes").load(live)
    key = ["case_id", "line"]
    check(streamed.count() == streamed.select(*key).distinct().count(), "the stream wrote a line twice")
    diff = streamed.select(*batch.columns).exceptAll(batch).count() + batch.exceptAll(streamed.select(*batch.columns)).count()
    check(diff == 0, f"the stream's rows should equal the batch reader's rows for the same folder ({diff} differ)")
    return f"{len(first)} + {len(second)} + {len(third)} batches, stream == batch, {streamed.count()} rows"


def stage_logs(ctx):
    spark = ctx["spark"]
    spark.conf.set("spark.sql.pyspark.worker.logging.enabled", "true")
    try:
        spark.read.format("casefile").option("table", "cases").load(DATA).collect()
        spark.read.format("casefile").option("table", "attachments").load(DATA).collect()
        expected = {"CASE-0004 missing_attachment", "CASE-0005 unlisted_attachment", "CASE-0008 bad_index",
                    "CASE-0010 bad_priority", "CASE-0004 missing scan.png", "CASE-0006 sha_mismatch receipt.pdf"}
        seen = set()
        for _ in range(30):    # worker logs arrive asynchronously (see "Packaging, Registration, ...")
            seen = {r["msg"] for r in spark.tvf.python_worker_logs().filter("logger = 'casefile'").collect()}
            if expected <= seen:
                break
            time.sleep(0.5)
    finally:
        spark.conf.set("spark.sql.pyspark.worker.logging.enabled", "false")
    check(expected <= seen, f"logger 'casefile' should warn about every problem; missing: {sorted(expected - seen)}")
    return f"{len(seen)} distinct warnings from executors"


MUTANTS = {
    "a planner that ignores the byte target": ("plan_by_bytes", lambda real: (
        lambda items, target: [[k for k, _ in sorted(items, key=lambda kv: (-kv[1], kv[0]))]] if items else [])),
    "a planner that splits by count, not bytes": ("plan_by_bytes", lambda real: (
        lambda items, target: [[k for k, _ in sorted(items)][i::2] for i in range(2) if sorted(items)[i::2]])),
    "an index parser that forgets the BOM": ("parse_index", lambda real: (
        lambda raw, folder: real(raw, folder) if not raw.startswith(b"\xef\xbb\xbf")
        else {**real(b"{", folder)})),
    "an index parser that treats version 1 as broken": ("parse_index", lambda real: (
        lambda raw, folder: (lambda r: {**real(b"{", folder)} if r["schema_version"] == 1 else r)(real(raw, folder)))),
    "an index parser that ignores time zone offsets": ("parse_index", lambda real: (
        lambda raw, folder: (lambda r: {**r, "opened": r["opened"].replace(hour=(r["opened"].hour + 2) % 24)}
                             if r["opened"] is not None and b"+02:00" in raw else r)(real(raw, folder)))),
    "an index parser that accepts any priority": ("parse_index", lambda real: (
        lambda raw, folder: (lambda r: {**r, "problems": [p for p in r["problems"] if p != "bad_priority"]})(
            real(raw, folder)))),
    "a change parser that keeps the \\r of CRLF lines": ("parse_change_line", lambda real: (
        lambda line: (lambda r: {**r, "actor": r["actor"] + "\r"} if r and line.endswith("\r") else r)(real(line)))),
    "a change parser that accepts lines without an arrow": ("parse_change_line", lambda real: (
        lambda line: real(line) or {"ts": None, "field": "?", "old": None, "new": None, "actor": None})),
    "a checksum check that always says ok": ("attachment_status", lambda real: (
        lambda expected, actual, listed, on_disk: "ok" if listed and on_disk else real(expected, actual, listed, on_disk))),
}


def run_offline_suite():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OfflineTests)
    result = unittest.TestResult()
    suite.run(result)
    return result


def stage_offline_tests(ctx):
    from pyspark import SparkContext

    check(SparkContext._active_spark_context is None, "offline tests must run before any SparkSession exists")
    result = run_offline_suite()
    check(result.testsRun >= 5, f"write at least 5 tests in OfflineTests, found {result.testsRun}")
    problems = [f"{t.id()}: {tb.strip().splitlines()[-1]}" for t, tb in result.failures + result.errors]
    check(not problems, "your offline tests should pass on your code:\n  " + "\n  ".join(problems))
    check(SparkContext._active_spark_context is None, "offline tests must not start Spark")
    survivors = []
    g = globals()
    for label, (name, make) in MUTANTS.items():
        real = g[name]
        g[name] = make(real)
        try:
            if run_offline_suite().wasSuccessful():
                survivors.append(label)
        finally:
            g[name] = real
    check(not survivors, "your tests did not catch: " + "; ".join(survivors))
    return f"{result.testsRun} tests, {len(MUTANTS)} broken versions caught"


def stage_design_review(ctx):
    text = DESIGN_REVIEW
    check("TODO" not in text, "DESIGN_REVIEW still contains TODO")
    sections = {}
    for part in re.split(r"^## ", text, flags=re.M)[1:]:
        title, _, body = part.partition("\n")
        sections[title.strip().lower()] = body
    required = ["decisions", "trade-offs", "failure modes", "testing", "what i would change for production"]
    missing = [s for s in required if s not in sections]
    check(not missing, f"DESIGN_REVIEW needs the sections {required}; missing {missing}")
    for s in required:
        words = len(sections[s].split())
        check(words >= 30, f"section '{s}' has {words} words; explain your reasoning (30 or more)")
    bullets = [l for l in sections["failure modes"].splitlines() if l.strip().startswith("- ")]
    check(len(bullets) >= 4, f"list at least 4 failure modes as '- ' bullets, found {len(bullets)}")
    decisions = sections["decisions"].lower()
    for topic in ("partition", "offset", "manifest", "variant"):
        check(topic in decisions, f"the Decisions section should explain your choice about '{topic}'")
    return "all sections present"


def explain_error(e):
    """The most useful line of an exception, even when it comes from a Python worker."""
    text = str(e)
    todo = re.search(r"TODO: [^\n]*", text) or re.search(r"TODO\b[^\n]*", text)
    if todo:
        return todo.group(0)[:400]
    errors = [l.strip() for l in text.splitlines() if re.match(r"\s*[\w.]*(Error|Exception): ", l)]
    if errors:
        return errors[-1][:400]
    first = next((l for l in text.splitlines() if l.strip()), "")
    return f"{type(e).__name__}: {first[:400]}"


STAGES = [("parsing", stage_parsing), ("planning", stage_planning), ("offline_tests", stage_offline_tests),
          ("design_review", stage_design_review), ("batch", stage_batch), ("variant", stage_variant),
          ("pushdown", stage_pushdown), ("writer", stage_writer), ("streaming", stage_streaming),
          ("logs", stage_logs)]
SPARK_STAGES = {"batch", "variant", "pushdown", "writer", "streaming", "logs"}

if __name__ == "__main__":
    selected = [(n, f) for n, f in STAGES if ONLY is None or n in ONLY]
    results, ctx = [], {}
    try:
        for name, fn in selected:
            if name in SPARK_STAGES and "spark" not in ctx:
                ctx["spark"] = (SparkSession.builder.master("local[2]").appName("FinalProject")
                                .config("spark.sql.session.timeZone", "UTC")
                                .config("spark.sql.shuffle.partitions", "4")
                                .config("spark.sql.python.filterPushdown.enabled", "true")
                                .getOrCreate())
                ctx["spark"].sparkContext.setLogLevel("ERROR")
                ctx["spark"].dataSource.register(CaseFileSource)
            start = time.monotonic()
            try:
                detail = fn(ctx)
                results.append((name, True, detail))
            except AssertionError as e:
                results.append((name, False, str(e)))
            except Exception as e:  # noqa: BLE001
                results.append((name, False, explain_error(e)))
            print(f"{'PASS' if results[-1][1] else 'FAIL'}  {name:14} {time.monotonic() - start:5.1f}s  {results[-1][2]}",
                  flush=True)
    finally:
        if "spark" in ctx:
            ctx["spark"].stop()

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} stages passed")
    if failed:
        sys.exit(f"Stages still failing: {', '.join(failed)}")
    if ONLY is not None:
        sys.exit("The selected stages pass. Set ONLY = None to grade every stage.")
    print("All tests passed!")
