"""
Shipping Python Dependencies to a Cluster - Exercise

A small pure-Python package, `messytools`, cleans messy person names. The
harness writes it to a temporary folder that is NOT on the driver's
sys.path, so the only way an executor can import it is if you ship it.
You ship it three ways and prove, from inside the tasks, where Python
found it:

1. A zip on the Python path of every task: SparkContext.addPyFile
   (the same mechanism as --py-files and spark.submit.pyFiles).
2. An archive unpacked on every executor: spark.archives with a
   "#deps" fragment, laid out like `pip install --target`.
3. Spark Connect artifacts: spark.addArtifacts(..., pyfile=True), which
   are private to one Connect session.

Along the way the harness checks two traps from the lesson: a UDF that
was used before addPyFile keeps the include list it captured, and two
Connect sessions can run two versions of the same package side by side.
"""

import os
import re
import shutil
import tarfile
import tempfile
import zipfile

from pyspark import SparkFiles
from pyspark.sql import SparkSession, functions as F

# ---- The package to ship (given) ----
PACKAGE = {
    "messytools/__init__.py": (
        'VERSION = "{version}"\n'
        "from messytools.names import clean_name\n"
    ),
    "messytools/names.py": (
        "import unicodedata\n"
        "\n"
        "\n"
        "def clean_name(s):\n"
        '    """NFKC-normalize, trim, collapse spaces and title-case a name."""\n'
        "    if s is None:\n"
        "        return None\n"
        '    s = unicodedata.normalize("NFKC", s).replace("\\ufeff", "")\n'
        '    return " ".join(w.capitalize() for w in s.split())\n'
    ),
}

NAMES = ["  hoa   KIM", "﻿EMMA patel ", "ｃhloe  tran", "rosa\tGARCIA"]
EXPECTED_CLEAN = ["Hoa Kim", "Emma Patel", "Chloe Tran", "Rosa Garcia"]


def write_package(root, version):
    """Write messytools (with VERSION = version) under root; return root."""
    for rel, text in PACKAGE.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text.format(version=version))
    # A stray bytecode cache, as an editor or a test run leaves behind
    os.makedirs(os.path.join(root, "messytools", "__pycache__"), exist_ok=True)
    with open(os.path.join(root, "messytools", "__pycache__", "names.cpython-312.pyc"), "wb") as f:
        f.write(b"\x00not real bytecode")
    return root


# ---- 1. Build a zip that Python can import from ----
def build_zip(src_dir, zip_path):
    """Zip the package folder(s) in src_dir so that zip_path is importable.

    Entries must be relative to src_dir (messytools/__init__.py at the top
    level), and __pycache__ folders and .pyc files must be left out.
    Return zip_path.
    """
    # TODO: zipfile.ZipFile + os.walk; name each entry relative to src_dir;
    # skip __pycache__ folders and .pyc files
    return None


# ---- 2. Build an archive laid out like `pip install --target` ----
def build_site_archive(src_dir, tar_path):
    """Write a .tar.gz whose single top-level folder is site-packages/,
    holding the package (site-packages/messytools/__init__.py, ...), with
    no __pycache__ entries. Return tar_path.
    """
    # TODO: tarfile.open(tar_path, "w:gz"); add each entry of src_dir under
    # arcname site-packages/<entry>, with a filter that drops __pycache__
    return None


# ---- 3. Ask the executors where they found the package ----
def where_imported(spark, archive_name=None):
    """Send NAMES through tasks (a DataFrame of NAMES, repartition(4)) where
    a UDF imports messytools and reports what it found.

    If archive_name is given, the task first puts
    <SparkFiles.get(archive_name)>/site-packages at the front of sys.path.
    Build the UDF inside this function, so every call gets a fresh one.

    Return a list of dicts sorted by "raw", one per name, with keys:
      raw, cleaned, version, file, pid
    and cleaned/version/file set to None when the import fails.
    Must work in Classic and in Spark Connect.
    """
    # TODO: a @F.udf returning a struct (cleaned, version, file, pid) that
    # imports messytools inside the task (catch ImportError), and for an
    # archive first adds <SparkFiles.get(archive_name)>/site-packages to sys.path
    return None


# ---- 4. Read what a classic UDF captured ----
def captured_includes(udf_wrapper):
    """For a UDF made with @F.udf in Classic mode, return the list of
    Python includes (zip/egg/jar file names) captured by its JVM
    PythonFunction, as Python strings.
    """
    # TODO: udf_wrapper._unwrapped._judf is the JVM UserDefinedPythonFunction;
    # its func() has pythonIncludes()
    return None


def error_condition(action):
    """(Given, from "Packaging, Registration, Testing and Debugging".)
    Run action(); return None, or the error's condition name."""
    try:
        action()
    except Exception as e:
        get = getattr(e, "getCondition", None)
        name = get() if get else None
        if name:
            return name
        m = re.search(r"\[([A-Z][A-Z0-9_]+)(?:\.[A-Z0-9_]+)?\]", str(e))
        return m.group(1) if m else type(e).__name__
    return None


# ---- Harness ----
def check_found(rows, version, path_must_contain, label):
    assert len(rows) == len(NAMES), f"{label}: expected {len(NAMES)} rows, got {len(rows)}"
    for r in rows:
        assert r["file"] is not None, (
            f"{label}: a task could not import messytools for {r['raw']!r}. "
            "Was the package shipped before the query ran?")
        assert path_must_contain in r["file"], (
            f"{label}: messytools came from {r['file']}, expected a path containing "
            f"{path_must_contain!r}")
        assert r["version"] == version, f"{label}: got VERSION {r['version']}, expected {version}"
    got = sorted(r["cleaned"] for r in rows)
    assert got == sorted(EXPECTED_CLEAN), f"{label}: clean_name gave {got}"


def short(path):
    """Shorten a SparkFiles path for printing."""
    return re.sub(r".*/userFiles-[0-9a-f-]+/", "<root>/", path or "None")


if __name__ == "__main__":
    work = tempfile.mkdtemp(prefix="ship_")

    # --- Build the artifacts, without Spark ---
    src_v1 = write_package(os.path.join(work, "src_v1"), "1.0")
    zip_path = build_zip(src_v1, os.path.join(work, "messytools.zip"))
    assert zip_path and os.path.exists(zip_path), "build_zip must write the zip and return its path"
    names = zipfile.ZipFile(zip_path).namelist()
    assert "messytools/__init__.py" in names, (
        f"The zip must have messytools/__init__.py at its top level; it has {names}. "
        "Use paths relative to src_dir as the names inside the zip.")
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names), (
        f"Leave __pycache__ and .pyc files out of the zip: {names}")
    assert not any(n.startswith("/") for n in names), "Zip entry names must be relative"

    src_v11 = write_package(os.path.join(work, "src_v11"), "1.1")
    tar_path = build_site_archive(src_v11, os.path.join(work, "deps.tar.gz"))
    assert tar_path and os.path.exists(tar_path), "build_site_archive must return the archive path"
    members = tarfile.open(tar_path).getnames()
    assert "site-packages/messytools/__init__.py" in members, (
        f"The archive must contain site-packages/messytools/__init__.py; it has {members}")
    assert not any("__pycache__" in m for m in members), f"Leave __pycache__ out: {members}"
    print(f"zip entries: {names}")
    print(f"archive entries: {[m for m in members if m.endswith('.py')]}")

    # --- Way 1: addPyFile (Classic) ---
    spark = SparkSession.builder.master("local[2]").appName("ship").getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")

    before = where_imported(spark)
    assert before is not None, "where_imported must return a list of dicts"
    assert all(r["file"] is None for r in before), (
        "Before shipping, tasks should NOT find messytools. If they do, it is "
        f"installed somewhere on the executors' path: {before[0]['file']}")
    print("\nBefore shipping: tasks cannot import messytools (as expected)")

    @F.udf("string")
    def early(s):
        return s

    spark.range(1).select(early(F.lit("x"))).collect()  # creates early's JVM function now

    spark.sparkContext.addPyFile(zip_path)

    @F.udf("string")
    def late(s):
        return s

    spark.range(1).select(late(F.lit("x"))).collect()
    early_inc, late_inc = captured_includes(early), captured_includes(late)
    assert early_inc == [], (
        f"A UDF used before addPyFile should have captured no includes, got {early_inc}")
    assert late_inc == ["messytools.zip"], (
        f"A UDF created after addPyFile should carry ['messytools.zip'], got {late_inc}")
    print(f"includes captured: early UDF {early_inc}, late UDF {late_inc}")

    rows = where_imported(spark)
    check_found(rows, "1.0", "messytools.zip/messytools/__init__.py", "addPyFile")
    root = SparkFiles.getRootDirectory()
    assert all(r["file"].startswith(root) for r in rows), "The zip should be read from SparkFiles' root"
    pids_classic = {r["pid"] for r in rows}
    print("addPyFile: every task imported", short(rows[0]["file"]), "VERSION", rows[0]["version"])
    spark.stop()

    # --- Way 2: spark.archives (Classic, set before the context starts) ---
    spark = (SparkSession.builder.master("local[2]").appName("ship-archive")
             .config("spark.archives", tar_path + "#deps")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    rows = where_imported(spark, archive_name="deps")
    check_found(rows, "1.1", "/deps/site-packages/messytools/__init__.py", "spark.archives")
    assert {r["pid"] for r in rows}.isdisjoint(pids_classic), (
        "A new SparkContext should start new Python workers")
    print("spark.archives: every task imported", short(rows[0]["file"]), "VERSION", rows[0]["version"])
    spark.stop()

    # --- Way 3: Spark Connect artifacts, one version per session ---
    src_v2 = write_package(os.path.join(work, "src_v2"), "2.0")
    src_v3 = write_package(os.path.join(work, "src_v3"), "3.0")
    os.makedirs(os.path.join(work, "a"))
    os.makedirs(os.path.join(work, "b"))
    zip_a = build_zip(src_v2, os.path.join(work, "a", "messytools.zip"))
    zip_b = build_zip(src_v3, os.path.join(work, "b", "messytools.zip"))

    # spark-submit already sets a master, so ask for Connect with spark.api.mode
    # (builder.remote("local[2]") is refused with CANNOT_CONFIGURE_SPARK_CONNECT_MASTER)
    spark_a = (SparkSession.builder.master("local[2]")
               .config("spark.api.mode", "connect").getOrCreate())
    # A second, independent client session on the same server. The Connect
    # builder is used directly because the classic builder refuses a remote
    # URL while spark-submit's master is set.
    from pyspark.sql.connect.session import SparkSession as ConnectSession

    url = "sc://" + spark_a.client._builder.endpoint
    spark_b = ConnectSession.builder.remote(url).create()
    assert spark_a.session_id != spark_b.session_id

    spark_a.addArtifacts(zip_a, pyfile=True)
    spark_b.addArtifacts(zip_b, pyfile=True)
    rows_a, rows_b = where_imported(spark_a), where_imported(spark_b)
    check_found(rows_a, "2.0", "messytools.zip/messytools/__init__.py", "Connect session A")
    check_found(rows_b, "3.0", "messytools.zip/messytools/__init__.py", "Connect session B")
    dir_a = os.path.dirname(rows_a[0]["file"].split("/messytools.zip/")[0] + "/x")
    dir_b = os.path.dirname(rows_b[0]["file"].split("/messytools.zip/")[0] + "/x")
    assert dir_a != dir_b, "Each Connect session should get its own artifact folder"
    assert {r["pid"] for r in rows_a}.isdisjoint({r["pid"] for r in rows_b}), (
        "Each Connect session should get its own Python workers")
    print("Connect A:", short(rows_a[0]["file"]), "VERSION", rows_a[0]["version"])
    print("Connect B:", short(rows_b[0]["file"]), "VERSION", rows_b[0]["version"])

    # Same name, new content: refused on Connect
    shutil.copy(zip_b, zip_a)
    cond = error_condition(lambda: spark_a.addArtifacts(zip_a, pyfile=True))
    assert cond == "ARTIFACT_ALREADY_EXISTS", (
        f"Re-adding messytools.zip with new content should fail with "
        f"ARTIFACT_ALREADY_EXISTS, got {cond}")
    print("Re-adding a changed messytools.zip:", cond)

    # spark.stop() on a Connect session in this process also stops the local
    # server, and a client left open would then retry RPCs at exit. So release
    # and close B by hand, and stop A (which owns the server) last.
    spark_b.client.release_session()
    spark_b.client.close()
    spark_a.stop()
    print("\nAll tests passed!")
