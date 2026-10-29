"""
Determinism, Retries and Fault Injection - Solution

A small batch job turns the checkout service's events
(data/messy/checkout_events/drop_*.jsonl) into a table of charges: one row
per "pay" event with a charge id, the amount converted by a (fake) payment
service, and an audit sample. It also posts every charge to a ledger and
reports how many charges it produced.

The harness runs the job twice:

- a clean run: local[2], default partitioning, no failures;
- a chaos run in a fresh session: local[4,4] (task retries allowed), tiny
  input splits and a different number of shuffle partitions, the payment
  service failing the first attempt of every task, and the whole job run
  twice in a row as a scheduler would after a crash.

Every output of the chaos run must be identical to the clean run: the
charges table, the audit sample, the ledger (each charge exactly once)
and the reported metrics.
"""

import json
import os
import shutil
import tempfile

from pyspark import TaskContext
from pyspark.sql import Observation, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType

EVENT_SCHEMA = ("event_id STRING, user STRING, action STRING, page STRING, "
                "ts TIMESTAMP, amount DOUBLE")
CHAOS_FLAG = os.path.abspath("_chaos_on")          # exists only during the chaos run
SERVICE_LOG = os.path.abspath("_service_calls.log")


# ---- The payment service (given; do not change) ----
def call_service(amount):
    """Convert CAD to USD. In the chaos run, the first attempt of every
    task fails after a few calls, the way a flaky network does."""
    ctx = TaskContext.get()
    with open(SERVICE_LOG, "a") as f:
        f.write(f"{ctx.stageId()} {ctx.partitionId()} {ctx.attemptNumber()}\n")
    if os.path.exists(CHAOS_FLAG) and ctx.attemptNumber() == 0:
        raise ConnectionError("payment service timed out (injected)")
    return round(amount * 0.73, 2)


# ---- 1. A charge id that is the same in every run ----
def with_charge_id(df):
    """Add charge_id: a stable id for the pay event, derived from its
    content (never from position, partitioning or a random seed)."""
    return df.withColumn(
        "charge_id", F.sha2(F.concat_ws("|", "event_id", "user"), 256).substr(1, 16))


# ---- 2. An audit sample that does not depend on partitioning ----
def audit_sample(df):
    """Roughly half of the charges, chosen by a hash of charge_id."""
    return df.where(F.pmod(F.xxhash64("charge_id"), F.lit(2)) == 0)


# ---- 3. A conversion UDF without side effects ----
def _to_usd(amount):
    return call_service(amount)


# A DataType, not the DDL string "double": parsing DDL needs a running
# session, and this line runs at import time, before the session exists.
to_usd = F.udf(_to_usd, DoubleType())


# ---- 4. The job ----
def post_ledger(spark, charges_dir, ledger_path):
    """Post each committed charge to the ledger exactly once.

    The ledger is a JSON Lines file, one posting per line:
    {"charge_id": ..., "amount_usd": ...}. This runs on the driver after the
    write committed, keys the postings by charge_id and replaces the file
    in one rename, so running it again changes nothing.
    """
    postings = {}
    if os.path.exists(ledger_path):
        with open(ledger_path) as f:
            for line in f:
                p = json.loads(line)
                postings[p["charge_id"]] = p["amount_usd"]
    for r in spark.read.parquet(charges_dir).select("charge_id", "amount_usd").collect():
        postings[r.charge_id] = r.amount_usd
    tmp = ledger_path + ".tmp"
    with open(tmp, "w") as f:
        for cid in sorted(postings):
            f.write(json.dumps({"charge_id": cid, "amount_usd": postings[cid]}) + "\n")
    os.replace(tmp, ledger_path)


def run_job(spark, src_dir, out_dir, ledger_path):
    """Build the charges and audit tables, post the ledger, return metrics."""
    events = spark.read.schema(EVENT_SCHEMA).json(src_dir)
    charges = (with_charge_id(events.where("action = 'pay'").dropDuplicates(["event_id"]))
               .withColumn("amount_usd", to_usd("amount"))
               .select("charge_id", "event_id", "user", "ts", "amount", "amount_usd"))
    obs = Observation("charges")
    charges = charges.observe(obs, F.count(F.lit(1)).alias("charges"),
                              F.round(F.sum("amount_usd"), 2).alias("revenue_usd"))
    charges_dir = os.path.join(out_dir, "charges")
    charges.write.mode("overwrite").parquet(charges_dir)
    metrics = obs.get
    audit_sample(spark.read.parquet(charges_dir)).write.mode("overwrite").parquet(
        os.path.join(out_dir, "audit"))
    post_ledger(spark, charges_dir, ledger_path)
    return {"charges": metrics["charges"], "revenue_usd": metrics["revenue_usd"]}


# ---- Harness (given) ----
def snapshot(spark, out_dir, ledger_path, metrics):
    """Everything the job produced, in a comparable form."""
    rows = lambda name: sorted(tuple(r) for r in spark.read.parquet(
        os.path.join(out_dir, name)).select("charge_id", "event_id", "amount_usd").collect())
    with open(ledger_path) as f:
        ledger = sorted((p["charge_id"], p["amount_usd"]) for p in map(json.loads, f))
    return {"charges": rows("charges"), "audit": rows("audit"),
            "ledger": ledger, "metrics": metrics}


def new_session(master, **conf):
    builder = SparkSession.builder.master(master).appName("determinism_retries")
    for k, v in conf.items():
        builder = builder.config(k, v)
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("OFF")
    return spark


def service_attempts():
    with open(SERVICE_LOG) as f:
        return [tuple(map(int, line.split())) for line in f if line.strip()]


if __name__ == "__main__":
    src = "data/messy/checkout_events"
    pays = {}
    for name in sorted(os.listdir(src)):
        with open(os.path.join(src, name)) as f:
            for line in f:
                e = json.loads(line)
                if e["action"] == "pay":
                    pays[e["event_id"]] = e["amount"]
    expected_metrics = {"charges": len(pays),
                        "revenue_usd": round(sum(round(a * 0.73, 2) for a in pays.values()), 2)}
    work = tempfile.mkdtemp(prefix="determinism_")
    for p in (CHAOS_FLAG, SERVICE_LOG):
        if os.path.exists(p):
            os.remove(p)

    # --- Clean run ---
    print("Clean run: local[2], no failures")
    spark = new_session("local[2]", **{"spark.sql.session.timeZone": "UTC"})
    clean_out, clean_ledger = os.path.join(work, "clean"), os.path.join(work, "clean_ledger.json")
    metrics = run_job(spark, src, clean_out, clean_ledger)
    assert metrics is not None, "run_job() returned None. Return the metrics dict."
    clean = snapshot(spark, clean_out, clean_ledger, metrics)
    print(f"  metrics: {metrics}")
    print(f"  charges: {len(clean['charges'])}, audit sample: {len(clean['audit'])}, "
          f"ledger entries: {len(clean['ledger'])}")
    assert metrics == expected_metrics, (
        f"The metrics should be {expected_metrics} (each pay event once, converted), got "
        f"{metrics}. A count that is a multiple of the true one means something ran the "
        "conversion more than once (a second action, or an accumulator in a UDF).")
    assert len(clean["charges"]) == expected_metrics["charges"], (
        f"Expected {expected_metrics['charges']} charges (re-sent events count once), "
        f"got {len(clean['charges'])}")
    assert 0 < len(clean["audit"]) < len(clean["charges"]), (
        f"The audit sample should hold some but not all charges, got {len(clean['audit'])}")
    assert len(clean["ledger"]) == len(clean["charges"]) == len({c for c, _ in clean["ledger"]}), (
        f"The clean run's ledger has {len(clean['ledger'])} postings for "
        f"{len(clean['charges'])} charges. Each charge must be posted exactly once, even "
        "without failures: is something running the conversion twice?")
    ids = [c[0] for c in clean["charges"]]
    assert len(set(ids)) == len(ids), "charge_id must be unique per charge"
    spark.stop()

    # --- Chaos run ---
    print("Chaos run: local[4,4], tiny splits, 7 shuffle partitions, "
          "a failure in every first attempt, the job run twice")
    open(CHAOS_FLAG, "w").close()
    os.remove(SERVICE_LOG)
    spark = new_session("local[4,4]", **{
        "spark.sql.session.timeZone": "UTC",
        "spark.sql.files.maxPartitionBytes": "700",
        "spark.sql.files.openCostInBytes": "0",
        "spark.sql.shuffle.partitions": "7",
        "spark.sql.adaptive.enabled": "false"})
    chaos_out, chaos_ledger = os.path.join(work, "chaos"), os.path.join(work, "chaos_ledger.json")
    try:
        run_job(spark, src, chaos_out, chaos_ledger)
        metrics = run_job(spark, src, chaos_out, chaos_ledger)
    except Exception as e:  # noqa: BLE001
        raise AssertionError(
            "The job failed under injected failures. A task may fail and be retried; "
            "make sure nothing else breaks. Spark said:\n" + str(e).splitlines()[0][:500]) from None
    os.remove(CHAOS_FLAG)
    attempts = service_attempts()
    retried = sorted({(s, p) for s, p, a in attempts if a > 0})
    print(f"  service calls: {len(attempts)}, tasks retried: {len(retried)}")
    assert retried, "The chaos run should have retried tasks (the harness injects failures)"
    chaos = snapshot(spark, chaos_out, chaos_ledger, metrics)

    for key, what in [("charges", "charges table"), ("audit", "audit sample"),
                      ("ledger", "ledger"), ("metrics", "metrics")]:
        a, b = clean[key], chaos[key]
        if key == "ledger":
            assert len(b) == len(a) and len({c for c, _ in b}) == len(b), (
                f"The ledger has {len(b)} entries after the chaos run and {len(a)} after the clean "
                "run. Posting inside a UDF or a task repeats on every retry and every rerun; post "
                "from the driver, after the write, keyed by charge_id.")
        assert a == b, (
            f"The {what} differs between the clean run and the chaos run.\n"
            f"  clean: {str(a)[:300]}\n  chaos: {str(b)[:300]}\n"
            + {"charges": "Is charge_id derived from content only, and does a rerun replace "
                          "the output instead of appending to it?",
               "audit": "Does the sample depend on partitioning or row order (sample() with a "
                        "seed does)? Choose rows by a hash of charge_id.",
               "ledger": "Each charge must be posted exactly once with the same amount.",
               "metrics": "Count with observe() on the write, not with an accumulator or a "
                          "second action."}[key])
    print(f"  charges, audit sample, ledger and metrics identical to the clean run")
    spark.stop()
    shutil.rmtree(work, ignore_errors=True)
    os.remove(SERVICE_LOG)
    print("All tests passed!")
