"""
The Python Worker Protocol - Exercise

Experiments on Spark's Python workers: worker reuse seen through process IDs,
closure size and the broadcast threshold, classifying worker failures, and a
wire tap that records the exact bytes the JVM and a Python worker exchange,
decoded with a strict frame reader.
"""

import glob
import io
import json
import os
import shutil
import struct
import tempfile
import time

import pyarrow as pa
from pyspark.serializers import CloudPickleSerializer
from pyspark.sql import SparkSession, functions as F

# From SpecialLengths in core/.../api/python/PythonRunner.scala (4.2.0).
END_OF_DATA_SECTION = -1
PYTHON_EXCEPTION_THROWN = -2
TIMING_DATA = -3
END_OF_STREAM = -4
NULL = -5
START_ARROW_STREAM = -6

SQL_BATCHED_UDF = 100
SQL_ARROW_BATCHED_UDF = 101


class ProtocolError(Exception):
    pass


class FrameReader:
    """A strict reader over a byte buffer, with the encodings of
    pyspark/serializers.py: big-endian int (4 bytes), long (8), bool (1),
    and length-prefixed bytes / UTF-8 strings."""

    def __init__(self, data):
        self.data, self.pos = data, 0

    def remaining(self):
        return len(self.data) - self.pos

    def take(self, n):
        if n < 0 or n > self.remaining():
            raise ProtocolError(f"asked for {n} bytes at offset {self.pos}, "
                                f"{self.remaining()} left")
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def int(self):
        return struct.unpack("!i", self.take(4))[0]

    def long(self):
        return struct.unpack("!q", self.take(8))[0]

    def bool(self):
        return struct.unpack("!?", self.take(1))[0]

    def bytes(self):
        return self.take(self.int())

    def utf(self):
        return self.bytes().decode("utf-8")


# ---------------------------------------------------------------------------
# Part 1: worker reuse
# ---------------------------------------------------------------------------

def worker_pids(spark, jobs=3):
    """Run `jobs` jobs of 4 tasks each and return, per job, the set of
    Python worker process IDs that evaluated a UDF."""
    # TODO: a UDF that returns os.getpid(); for each job, run it over
    # spark.range(0, 8, 1, 4) and collect the distinct PIDs into a set.
    return None



# ---------------------------------------------------------------------------
# Part 2: closure size
# ---------------------------------------------------------------------------

def shrink_closure(spark, stop_words):
    """A UDF is_stop(word) whose pickled command stays small: ship the set
    once as a broadcast variable instead of inside the function's closure."""
    # TODO: broadcast the set with spark.sparkContext.broadcast and read
    # .value inside the UDF, so the set is not pickled into the function.
    return None



# ---------------------------------------------------------------------------
# Part 3: classify failures
# ---------------------------------------------------------------------------

def classify_failure(exc):
    """'python_exception' when the UDF raised (PYTHON_EXCEPTION), 'idle_timeout'
    when Spark killed a silent worker, 'worker_crashed' when the process died,
    'other' for anything else."""
    # TODO: a raised exception has getCondition() == "PYTHON_EXCEPTION".
    # The other two only show up in the message text (a Py4JJavaError):
    # look for the sentences Spark uses; see the lesson.
    return None



# ---------------------------------------------------------------------------
# Part 4: decode the wire
# ---------------------------------------------------------------------------

def read_conf(r):
    return {r.utf(): r.utf() for _ in range(r.int())}


def parse_request(data):
    """Decode what the JVM sent to a worker for one UDF task.

    Order (BasePythonRunner.Writer.open, then writeCommand, the data, close):
    partition, Python version, task context JSON, Spark files root and
    includes, broadcasts, eval type, runner conf, eval conf, the UDFs, the
    input data, END_OF_STREAM.
    """
    r = FrameReader(data)
    req = {"partition": r.int(), "python_version": r.utf(),
           "task_context": json.loads(r.utf()), "files_root": r.utf()}
    req["includes"] = [r.utf() for _ in range(r.int())]
    if r.bool():
        raise ProtocolError("encrypted broadcasts are not supported by this reader")
    broadcasts = []
    for _ in range(r.int()):
        bid = r.long()
        broadcasts.append((bid, r.utf() if bid >= 0 else None))
    req["broadcasts"] = broadcasts
    req["eval_type"] = r.int()
    req["runner_conf"] = read_conf(r)
    req["eval_conf"] = read_conf(r)

    # TODO (UDF section, PythonUDFRunner.writeUDFs):
    #   int number of UDFs, then for each UDF:
    #     int number of arguments, then per argument: int offset, bool named,
    #       and if named a UTF name -> (offset, name or None)
    #     int number of chained functions, then each command as bytes
    #     long result id
    # store req["udfs"] = [{"args": [...], "commands": [...], "result_id": ...}]
    #
    # TODO (data section):
    #   SQL_BATCHED_UDF: frames (int length + bytes) until END_OF_DATA_SECTION;
    #     store req["frames"] = [bytes, ...]
    #   SQL_ARROW_BATCHED_UDF: an Arrow IPC stream with no length prefix:
    #     stream = io.BytesIO(data[r.pos:]); req["table"] =
    #     pa.ipc.open_stream(stream).read_all(); then r.pos += stream.tell()
    #   then the request must end with END_OF_STREAM and nothing after it
    #   (raise ProtocolError otherwise).
    return None



def parse_response(data):
    """Decode what a worker sent back: the results (pickled frames, or
    START_ARROW_STREAM and an Arrow stream), TIMING_DATA with boot, init and
    finish times (ms since the epoch) and processing ms, two spill counters,
    END_OF_DATA_SECTION, the accumulator updates and END_OF_STREAM."""
    # TODO: see the docstring and the lesson's annotated hexdump.
    # Return {"frames": [...], "table": None or pa.Table,
    #         "timing": {"boot", "init", "finish", "processing_ms"},
    #         "spill": {"memory", "disk"}, "accumulators": [...],
    #         "end_of_stream": True/False}
    return None



def rebuild_udf(command):
    """A UDF command is a CloudPickle of (function, return type)."""
    # TODO: unpickle with CloudPickleSerializer().loads and return the function.
    return None



# ---------------------------------------------------------------------------
# The wire tap (given): a worker module that records both directions
# ---------------------------------------------------------------------------

TAP_MODULE = r'''
import io, os
from pyspark.worker import main as real_main

class TeeIn(io.RawIOBase):
    def __init__(self, inner, log):
        self.inner, self.log = inner, log
    def readable(self):
        return True
    def readinto(self, b):
        data = self.inner.read1(len(b))   # read1: never wait for more than is there
        b[:len(data)] = data
        self.log.write(data)
        return len(data)

class TeeOut:
    def __init__(self, inner, log):
        self.inner, self.log = inner, log
    def write(self, data):
        self.log.write(data)
        return self.inner.write(data)
    def flush(self):
        self.log.flush()
        self.inner.flush()
    def __getattr__(self, name):
        return getattr(self.inner, name)

def main(infile, outfile):
    d, pid = os.environ["TAP_DIR"], os.getpid()
    with open(os.path.join(d, f"{pid}.in"), "ab") as i, open(os.path.join(d, f"{pid}.out"), "ab") as o:
        real_main(io.BufferedReader(TeeIn(infile, i), 65536), TeeOut(outfile, o))
'''


def tapped_run(spark, tapdir, query):
    for f in glob.glob(os.path.join(tapdir, "*.in")) + glob.glob(os.path.join(tapdir, "*.out")):
        os.remove(f)
    rows = query.collect()
    ins = sorted(glob.glob(os.path.join(tapdir, "*.in")))
    assert len(ins) == 1, f"expected one tapped worker, found {len(ins)}"
    return rows, open(ins[0], "rb").read(), open(ins[0][:-3] + ".out", "rb").read()


def desynced(data):
    """Rebuild a request the way the 4.2.0 columnar runner wrote it
    (SPARK-58241): the input schema JSON as a string before the UDF count."""
    r = FrameReader(data)
    r.int(); r.utf(); r.utf(); r.utf()
    [r.utf() for _ in range(r.int())]
    r.bool()
    for _ in range(r.int()):
        if r.long() >= 0:
            r.utf()
    r.int(); read_conf(r); read_conf(r)
    schema = b'{"type":"struct","fields":[{"name":"_0","type":"string","nullable":true,"metadata":{}}]}'
    return data[:r.pos] + struct.pack("!i", len(schema)) + schema + data[r.pos:]


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

def run_failure(spark, f):
    try:
        spark.range(1).select(F.udf(f, "long")("id")).collect()
    except Exception as e:  # noqa: BLE001 - we want to see every kind
        return e
    return None


if __name__ == "__main__":
    # ---- Session 1: defaults (daemon on, reuse on) ----
    spark = SparkSession.builder.master("local[2]").getOrCreate()
    spark.sparkContext.setLogLevel("OFF")

    pids = worker_pids(spark)
    assert pids is not None, "worker_pids returned None. Return a list of sets of PIDs."
    print("Worker PIDs per job with reuse on:", [sorted(p) for p in pids])
    assert len(pids) == 3 and all(isinstance(p, set) and p for p in pids), (
        f"worker_pids should return three non-empty sets, got {pids}")
    assert os.getpid() not in set().union(*pids), (
        "The PIDs include the driver's own Python process. Collect os.getpid() "
        "inside a UDF so it runs in a worker.")
    assert len(set().union(*pids)) <= 2, (
        f"With reuse on and local[2], at most 2 workers should serve every job; saw "
        f"{len(set().union(*pids))} PIDs.")

    # ---- Part 2: closure size ----
    # Under 1 MiB pickled, so Spark does not broadcast it for you
    # (spark.broadcast.UDFCompressionThreshold): every task carries it.
    stop = [f"word{i}" for i in range(60_000)]
    stop_set = set(stop)
    naive = F.udf(lambda w: w in stop_set, "boolean")
    naive_bytes = naive._unwrapped._judf.func().command().length()
    assert naive_bytes > 100_000, f"setup: the naive closure is only {naive_bytes} bytes"
    small = shrink_closure(spark, stop)
    assert small is not None, "shrink_closure returned None. Return a UDF."
    small_bytes = small._unwrapped._judf.func().command().length()
    print(f"Pickled command sent with each task: closure {naive_bytes} bytes, "
          f"broadcast {small_bytes} bytes")
    assert small_bytes < 4096, (
        f"The command is still {small_bytes} bytes. Do not capture the set in the "
        "closure; broadcast it and read bc.value inside the function.")
    got = spark.createDataFrame([("word7",), ("nope",)], "w string").select(small("w").alias("s"))
    assert [r.s for r in got.collect()] == [True, False], "shrink_closure gives wrong answers."

    # ---- Part 3: classify failures ----
    def boom(x):
        raise ValueError("bad row")

    def die(x):
        os._exit(3)

    def hang(x):
        time.sleep(300)

    raised, crashed = run_failure(spark, boom), run_failure(spark, die)
    spark.conf.set("spark.sql.execution.pyspark.udf.idleTimeoutSeconds", "3")
    spark.conf.set("spark.sql.execution.pyspark.udf.killOnIdleTimeout", "true")
    started = time.time()
    hung = run_failure(spark, hang)
    waited = time.time() - started
    spark.conf.unset("spark.sql.execution.pyspark.udf.idleTimeoutSeconds")
    spark.conf.unset("spark.sql.execution.pyspark.udf.killOnIdleTimeout")
    for exc, want in [(raised, "python_exception"), (crashed, "worker_crashed"),
                      (hung, "idle_timeout")]:
        assert exc is not None, f"The {want} case did not fail at all."
        got = classify_failure(exc)
        print(f"{type(exc).__name__:>18} -> {got}")
        assert got == want, (
            f"classify_failure returned {got!r} for a {type(exc).__name__}; expected "
            f"{want!r}. Check getCondition() first, then the message text.")
    assert waited < 60, "The hung UDF should have been killed after about 3 seconds."
    spark.stop()

    # ---- Session 2: reuse off, every worker tapped ----
    tapdir = tempfile.mkdtemp()
    with open(os.path.join(tapdir, "pyspark_tap.py"), "w") as f:
        f.write(TAP_MODULE)
    spark = (SparkSession.builder.master("local[2]")
             .config("spark.python.worker.reuse", "false")
             .config("spark.python.worker.module", "pyspark_tap")
             .config("spark.executorEnv.PYTHONPATH", tapdir)
             .config("spark.executorEnv.TAP_DIR", tapdir)
             .getOrCreate())
    spark.sparkContext.setLogLevel("OFF")

    pids = worker_pids(spark)
    print("Worker PIDs per job with reuse off:", [len(p) for p in pids], "distinct per job")
    assert all(len(p) == 4 for p in pids) and len(set().union(*pids)) == 12, (
        f"With reuse off every task should get a new worker (4 per job, 12 in all); "
        f"got {[sorted(p) for p in pids]}")

    words = spark.range(0, 3, 1, 1).selectExpr("concat('ab', id) AS s")
    rows, req_bytes, resp_bytes = tapped_run(
        spark, tapdir, words.select(F.udf(lambda s: s.upper(), "string", useArrow=False)("s")))
    print(f"Pickle UDF: {len(req_bytes)} bytes in, {len(resp_bytes)} bytes out")

    req = parse_request(req_bytes)
    assert req is not None, "parse_request returned None. Return a dict."
    assert req["partition"] == 0 and req["python_version"].count(".") == 1, (
        f"partition/python_version decoded as {req['partition']!r}/{req['python_version']!r}")
    assert req["task_context"]["partitionId"] == 0 and "stageId" in req["task_context"], (
        "task_context should be the decoded task context JSON")
    assert req["eval_type"] == SQL_BATCHED_UDF, f"eval_type decoded as {req['eval_type']}"
    assert len(req["udfs"]) == 1 and req["udfs"][0]["args"] == [(0, None)], (
        f"udfs decoded as {req['udfs']}")
    func = rebuild_udf(req["udfs"][0]["commands"][0])
    assert func is not None, "rebuild_udf returned None."
    assert func("abc") == "ABC", "The rebuilt function should upper-case its input."
    inputs = [CloudPickleSerializer().loads(fr) for fr in req["frames"]]
    print("Input frames, unpickled:", inputs)
    assert [v for frame in inputs for (v,) in frame] == ["ab0", "ab1", "ab2"]

    resp = parse_response(resp_bytes)
    assert resp is not None, "parse_response returned None. Return a dict."
    outputs = [CloudPickleSerializer().loads(fr) for fr in resp["frames"]]
    print("Output frames, unpickled:", outputs, "timing:", resp["timing"])
    assert [v for frame in outputs for v in frame] == [r[0] for r in rows] == ["AB0", "AB1", "AB2"]
    t = resp["timing"]
    assert t["boot"] <= t["init"] <= t["finish"] and t["processing_ms"] >= 0, (
        f"timing decoded as {t}; boot <= init <= finish (ms since the epoch)")
    assert resp["end_of_stream"] is True, "The response should end with END_OF_STREAM (-4)."

    rows, req_bytes, resp_bytes = tapped_run(
        spark, tapdir, words.select(F.udf(lambda s: s + "!", "string", useArrow=True)("s")))
    req, resp = parse_request(req_bytes), parse_response(resp_bytes)
    assert req["eval_type"] == SQL_ARROW_BATCHED_UDF
    print("Arrow UDF eval_conf keys:", sorted(req["eval_conf"]))
    assert "input_type" in req["eval_conf"], (
        "In 4.2 the Arrow UDF's input schema travels in eval_conf['input_type'].")
    assert req["table"].column(0).to_pylist() == ["ab0", "ab1", "ab2"]
    assert resp["table"].column(0).to_pylist() == ["ab0!", "ab1!", "ab2!"]

    try:
        parse_request(desynced(req_bytes))
    except ProtocolError as e:
        print("Desynced request rejected:", e)
    else:
        raise AssertionError("parse_request accepted a request with an extra string "
                             "before the UDF count; it must raise ProtocolError.")

    spark.stop()
    shutil.rmtree(tapdir)
    print("All tests passed!")
