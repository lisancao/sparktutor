"""
Model Inference in Production - Exercise

Label every support ticket with a remote classification service, the way a
production job has to: one HTTP client per partition, batched requests, a
client-side rate limit, retries with exponential backoff for the failures
that can heal, an idempotency key so a retry after a timeout is never paid
twice, a dead-letter table for the failures that cannot heal, and a result
cache keyed by a content hash and the model version so a rerun only asks
for what is new.

The "remote service" is a small HTTP server the harness starts on
127.0.0.1 with an ephemeral port. It misbehaves on purpose.
"""

import hashlib
import http.client
import json
import random
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pandas as pd
from pyspark.sql import SparkSession, functions as F

INBOX = "data/messy/support_tickets/inbox"
INBOX_SCHEMA = "ticket_id string, channel string, text string"
MODEL_VERSION = "kw-1"
NUM_TASKS = 4                  # partitions that call the service at the same time
BATCH_SIZE = 10                # items per HTTP request
REQUESTS_PER_SECOND = 2.0      # client-side limit, per task
MAX_ATTEMPTS = 4               # per item, counting the first try
TIMEOUT_SECONDS = 0.5          # per HTTP request
RESULT_SCHEMA = ("key string, label string, model_version string, status string, "
                 "attempts int, error string")


# ---- The remote service (given; the harness runs it) ----

class FakeClassifier:
    """A keyword "model" behind an HTTP API, with the failures real services have.

    POST /v1/classify with {"model": version, "items": [{"key": ..., "text": ...}]}
    and an Idempotency-Key header. Returns {"results": [...]}, one per item:
    {"key", "label", "model_version"} or {"key", "error", "retryable"}.

    - more than 16 requests in any second (all clients together): HTTP 429 with
      a Retry-After header
    - more than 20 items in one request: HTTP 413
    - an item whose text has no letters: a permanent error ("no text")
    - about one key in seven: "model busy" the first time it is seen (retryable)
    - about one request in five: the answer is ready but sent only after 1 second,
      longer than a sensible client timeout; a retry with the same
      Idempotency-Key gets the stored answer without running the model again
    """

    RULES = [("warranty", ["warranty", "broken", "repair", "defective", "crack", "batter", "stopped"]),
             ("returns", ["return", "refund", "exchange", "changed my mind", "send it back"]),
             ("shipping", ["ship", "deliver", "parcel", "track", "arrive", "express", "courier"]),
             ("privacy", ["privacy", "data", "unsubscribe", "delete", "account", "marketing"])]

    def __init__(self, version=MODEL_VERSION):
        self.version = version
        self.lock = threading.Lock()
        self.model_runs = Counter()        # key -> times the model actually ran on it
        self.items_received = Counter()    # key -> times it arrived in a request
        self.status = Counter()            # HTTP status codes sent
        self.requests = 0
        self.max_items = 0
        self.seen = set()
        self.slow_once = set()
        self.answers = {}                  # Idempotency-Key -> stored response body
        self.window = []                   # arrival times, for the rate limit

    def label(self, text):
        t = (text or "").lower()
        for label, words in self.RULES:
            if any(w in t for w in words):
                return label
        return "other"

    def handle(self, body, idem_key):
        """Returns (status, headers, payload, delay_seconds)."""
        now = time.monotonic()
        with self.lock:
            self.requests += 1
            self.window = [t for t in self.window if now - t < 1.0] + [now]
            if len(self.window) > 16:
                self.status[429] += 1
                return 429, {"Retry-After": "0.5"}, {"error": "rate limited"}, 0
            items = body.get("items", [])
            self.max_items = max(self.max_items, len(items))
            if len(items) > 20:
                self.status[413] += 1
                return 413, {}, {"error": "too many items"}, 0
            if idem_key and idem_key in self.answers:
                self.status[200] += 1
                return 200, {}, self.answers[idem_key], 0
            results = []
            for item in items:
                key, text = item["key"], item.get("text")
                self.items_received[key] += 1
                if not any(ch.isalpha() for ch in (text or "")):
                    results.append({"key": key, "error": "no text", "retryable": False})
                elif int(key[:8], 16) % 7 == 0 and key not in self.seen:
                    self.seen.add(key)
                    results.append({"key": key, "error": "model busy", "retryable": True})
                else:
                    self.seen.add(key)
                    self.model_runs[key] += 1
                    results.append({"key": key, "label": self.label(text), "model_version": self.version})
            payload = {"results": results}
            if idem_key:
                self.answers[idem_key] = payload
            delay = 0
            if idem_key and int(hashlib.sha256(idem_key.encode()).hexdigest()[:8], 16) % 5 == 0 \
                    and idem_key not in self.slow_once:
                self.slow_once.add(idem_key)
                delay = 1.0
            self.status[200] += 1
            return 200, {}, payload, delay

    def start(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                status, headers, payload, delay = service.handle(body, self.headers.get("Idempotency-Key"))
                if delay:
                    time.sleep(delay)
                data = json.dumps(payload).encode()
                try:
                    self.send_response(status)
                    for k, v in headers.items():
                        self.send_header(k, v)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass                     # the client gave up waiting

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


# ---- A small HTTP client (given) ----

class RetryableError(Exception):
    """The whole request failed in a way that may heal (429, 5xx, timeout, reset)."""
    def __init__(self, reason, retry_after=None):
        super().__init__(reason)
        self.retry_after = retry_after


class PermanentError(Exception):
    """The whole request was refused and retrying will not help (4xx other than 429)."""


class ServiceClient:
    """One keep-alive connection to the service. Create one per partition, never per row."""

    def __init__(self, url, timeout=TIMEOUT_SECONDS):
        u = urlparse(url)
        self.host, self.port, self.timeout = u.hostname, u.port, timeout
        self.conn = None

    def classify(self, items, model, idempotency_key):
        """POST the items; return the per-item result dicts, or raise one of the errors above."""
        body = json.dumps({"model": model, "items": items})
        try:
            if self.conn is None:
                self.conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
            self.conn.request("POST", "/v1/classify", body=body,
                              headers={"Content-Type": "application/json",
                                       "Idempotency-Key": idempotency_key})
            resp = self.conn.getresponse()
            data = resp.read()
        except (TimeoutError, ConnectionError, http.client.HTTPException, OSError) as e:
            self.close()                     # a timed-out connection cannot be reused
            raise RetryableError(f"{type(e).__name__}: {e}")
        if resp.status == 429 or resp.status >= 500:
            ra = resp.getheader("Retry-After")
            raise RetryableError(f"HTTP {resp.status}", float(ra) if ra else None)
        if resp.status != 200:
            raise PermanentError(f"HTTP {resp.status}: {data[:200]!r}")
        return json.loads(data)["results"]

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None


class RateLimiter:
    """At most `rate` calls per second from this task (a token bucket of size 1)."""

    def __init__(self, rate):
        self.interval = 1.0 / rate
        self.next_time = time.monotonic()

    def wait(self):
        now = time.monotonic()
        if now < self.next_time:
            time.sleep(self.next_time - now)
        self.next_time = max(now, self.next_time) + self.interval


def backoff_seconds(attempt, base=0.05, cap=2.0):
    """Exponential backoff with full jitter: a random wait in [0, base * 2**attempt], capped."""
    return random.uniform(0, min(cap, base * 2 ** attempt))


def idempotency_key(model, keys):
    """Same model and same items: same key, so a retry is recognized as a retry."""
    return hashlib.sha256((model + "|" + ",".join(sorted(keys))).encode()).hexdigest()


# ---- Your code ----

def with_content_key(tickets):
    """Add key: the SHA-256 (hex) of the ticket text, with NULL text treated as "".

    Two tickets with the same text get the same key, so they are classified once.
    """
    # TODO: return tickets with key = F.sha2(F.coalesce(F.col("text"), F.lit("")), 256)
    return None


def new_work(keyed, done, model_version=MODEL_VERSION):
    """Distinct (key, text) pairs that `done` has no row for with this model_version.

    done has at least the columns key and model_version (the cache and the
    dead-letter table together). Use a left anti join.
    """
    # TODO: keep the keys in done with this model_version
    # TODO: return keyed's distinct (key, text) rows (dropDuplicates(["key"])) without those keys (left_anti join)
    return None


def make_caller(url, model_version=MODEL_VERSION, batch_size=BATCH_SIZE, rate=REQUESTS_PER_SECOND,
                max_attempts=MAX_ATTEMPTS):
    """Return a function for mapInPandas: batches of (key, text) in, RESULT_SCHEMA rows out.

    For each partition: one ServiceClient and one RateLimiter (created inside the
    function, so each task builds its own). Send the items in chunks of batch_size,
    each request preceded by limiter.wait() and carrying idempotency_key(...) of its
    items. Per item, count attempts:
    - a result with a label: status "ok"
    - a result with retryable=False: status "failed" with its error, no retry
    - a result with retryable=True, or a RetryableError for the whole request: try
      the item again in a later request after backoff_seconds(attempt) (or
      retry_after if the error has one), until max_attempts, then "failed"
    - a PermanentError: every item in the request "failed"
    Close the client when the partition is done.
    """
    # TODO: define call(batches): create ServiceClient(url) and RateLimiter(rate) once, at the top
    # TODO: for each pandas DataFrame pdf: texts = dict(zip(pdf["key"], pdf["text"])), attempts per key, a pending list
    # TODO: while pending: take a chunk of batch_size, add 1 to each item's attempts, limiter.wait(), then
    # TODO:       client.classify(items, model_version, idempotency_key(model_version, chunk))
    # TODO:       RetryableError: put items with attempts < max_attempts back on pending after sleeping
    # TODO:             e.retry_after (if set) or backoff_seconds(attempt); the others are failed
    # TODO:       PermanentError: every item of the chunk is failed
    # TODO:       results: label -> ok; retryable=True and attempts left -> back on pending; else failed
    # TODO: yield a pd.DataFrame with RESULT_SCHEMA columns (attempts as pd.array(..., dtype="int32"))
    # TODO: close the client in a finally block, and return call
    return None


def run_inference(spark, tickets, url, cache_dir, dead_letter_dir, staging_dir,
                  model_version=MODEL_VERSION):
    """One run of the job. Returns the number of items sent to the service.

    1. keyed = with_content_key(tickets)
    2. done = cache rows and dead-letter rows (both have key, model_version); either
       folder may not exist yet on the first run
    3. work = new_work(keyed, done, model_version), repartitioned to NUM_TASKS
    4. results = work.mapInPandas(make_caller(url, model_version), RESULT_SCHEMA)
    5. Write results ONCE to staging_dir (overwrite), read them back, and from that
       copy append status "ok" rows to cache_dir and "failed" rows to dead_letter_dir
       (Parquet). Splitting `results` directly would call the service twice.
    """
    # TODO: read the cache and dead-letter Parquet folders with spark.read.schema(RESULT_SCHEMA); on the
    # TODO:       first run they do not exist yet (catch the error and use an empty DataFrame)
    # TODO: work = new_work(...).repartition(NUM_TASKS); return 0 when it is empty
    # TODO: results = work.mapInPandas(make_caller(url, model_version), RESULT_SCHEMA)
    # TODO: write results once to staging_dir, read that back, append ok rows to cache_dir and failed rows
    # TODO:       to dead_letter_dir; return the number of items in work
    return None


def labelled_tickets(spark, tickets, cache_dir, model_version=MODEL_VERSION):
    """ticket_id, label, model_version for every ticket with a cached result for this
    version (tickets in the dead-letter table are left out)."""
    # TODO: read cache_dir, keep model_version, one row per key, join to with_content_key(tickets) on key
    # TODO: select ticket_id, label, model_version
    return None


# ---- Test harness ----
if __name__ == "__main__":
    import os
    import shutil
    import tempfile

    spark = (SparkSession.builder
             .appName("InferenceInProduction")
             .master("local[*]")
             .config("spark.sql.shuffle.partitions", "4")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    work_dir = tempfile.mkdtemp()
    cache_dir = os.path.join(work_dir, "cache")
    dead_dir = os.path.join(work_dir, "dead_letter")
    service = FakeClassifier()
    url = service.start()

    def staging(name):
        return os.path.join(work_dir, "staging", name)

    try:
        tickets = spark.read.schema(INBOX_SCHEMA).json(INBOX).cache()
        texts = {r.ticket_id: r.text for r in tickets.collect()}
        distinct_texts = {t or "" for t in texts.values()}
        no_letters = {t for t in distinct_texts if not any(ch.isalpha() for ch in t)}

        # 1. Content keys
        keyed = with_content_key(tickets)
        assert keyed is not None, "with_content_key returned None"
        rows = keyed.collect()
        want = {r.ticket_id: hashlib.sha256((texts[r.ticket_id] or "").encode()).hexdigest() for r in rows}
        assert all(r.key == want[r.ticket_id] for r in rows), (
            "key should be sha2 of the text (NULL as \"\"), 256 bits, as hex")
        assert len({r.key for r in rows}) == len(distinct_texts), (
            f"Expected {len(distinct_texts)} distinct keys for {len(distinct_texts)} distinct texts")

        # 2. new_work
        empty = spark.createDataFrame([], RESULT_SCHEMA)
        w = new_work(keyed, empty)
        assert w is not None, "new_work returned None"
        assert sorted(w.columns) == ["key", "text"], f"new_work should return key, text; got {w.columns}"
        assert w.count() == len(distinct_texts), (
            f"With nothing done, new_work should return each distinct key once ({len(distinct_texts)}), "
            f"got {w.count()}")
        some = keyed.select("key").limit(5).withColumn("model_version", F.lit("kw-0"))
        assert new_work(keyed, some).count() == len(distinct_texts), (
            "Rows done with another model_version must not count as done")

        # 3. First run
        sent = run_inference(spark, tickets, url, cache_dir, dead_dir, staging("run1"))
        assert sent == len(distinct_texts), f"Run 1 should send {len(distinct_texts)} items, sent {sent}"
        cache = spark.read.parquet(cache_dir)
        dead = spark.read.parquet(dead_dir)
        n_ok, n_dead = cache.count(), dead.count()
        assert n_ok + n_dead == len(distinct_texts), (
            f"Every item should end in the cache or the dead-letter table: {n_ok} + {n_dead} "
            f"!= {len(distinct_texts)}")
        assert n_dead == len(no_letters), (
            f"Only the {len(no_letters)} texts without letters should be dead letters, got {n_dead}: "
            f"{[r.error for r in dead.collect()]}")
        assert all(r.error == "no text" for r in dead.collect()), (
            f"Dead letters should carry the service's error 'no text', got {[r.error for r in dead.collect()]}")
        resent = [r.key for r in dead.collect() if service.items_received[r.key] != 1]
        assert not resent, (
            f"{len(resent)} items with a non-retryable error were sent again; only retry items whose "
            "result says retryable=True")
        assert service.status[429] == 0, (
            f"The service answered 429 Too Many Requests {service.status[429]} times; "
            "call limiter.wait() before every request")
        assert service.max_items <= BATCH_SIZE, (
            f"A request carried {service.max_items} items; send at most BATCH_SIZE ({BATCH_SIZE})")
        busy = [k for k in service.seen if int(k[:8], 16) % 7 == 0]
        assert busy, "Expected some 'model busy' items in this data"
        retried = {r.key: r.attempts for r in cache.collect()}
        assert all(retried[k] >= 2 for k in busy if k in retried), (
            "Items that were 'model busy' the first time should have attempts >= 2")
        assert len(service.slow_once) > 0, "Expected some slow answers (timeouts) in this run"
        twice = [k for k, n in service.model_runs.items() if n > 1]
        assert not twice, (
            f"The model ran more than once for {len(twice)} keys; retries after a timeout must "
            "reuse the same Idempotency-Key (idempotency_key of the same model and keys)")
        requests_run1 = service.requests
        print(f"Run 1: {sent} items in {requests_run1} requests; {n_ok} ok, {n_dead} dead letters; "
              f"{sum(1 for a in retried.values() if a > 1)} items needed a retry; "
              f"{len(service.slow_once)} answers came too late")

        # 4. Second run: same tickets plus new ones; only the new ones are sent
        received_before = sum(service.items_received.values())
        new = spark.createDataFrame(
            [(f"N{i:03d}", "email", f"Order {5000 + i}: where is my parcel? tracking says nothing")
             for i in range(10)], INBOX_SCHEMA)
        more = tickets.unionByName(new)
        sent2 = run_inference(spark, more, url, cache_dir, dead_dir, staging("run2"))
        received = sum(service.items_received.values()) - received_before
        assert sent2 == 10, f"Run 2 should send only the 10 new tickets, sent {sent2}"
        assert received >= 10 and all(service.items_received[k] for k in
                                       [hashlib.sha256(t.encode()).hexdigest() for t in
                                        [f"Order {5000 + i}: where is my parcel? tracking says nothing"
                                         for i in range(10)]]), "The new tickets should reach the service"
        print(f"Run 2: sent {sent2} new items; cached and dead-letter items were not sent again")

        # 5. A new model version recomputes everything that has text
        service.version = "kw-2"
        sent3 = run_inference(spark, more, url, cache_dir, dead_dir, staging("run3"), model_version="kw-2")
        assert sent3 == len(distinct_texts) + 10, (
            f"A new model version should send every distinct text again ({len(distinct_texts) + 10}), sent {sent3}")
        labelled = labelled_tickets(spark, more, cache_dir, "kw-2")
        assert labelled is not None, "labelled_tickets returned None"
        lab = {r.ticket_id: r.label for r in labelled.collect()}
        assert len(lab) == len(texts) + 10 - sum(1 for t in texts.values() if (t or "") in no_letters), (
            f"Every ticket with text should have a kw-2 label, got {len(lab)}")
        assert all(lab[t] == service.label(texts[t]) for t in lab if t in texts), (
            "Labels should be the service's labels for each ticket's text")
        assert lab["N000"] == "shipping", f"N000 asks where a parcel is; expected shipping, got {lab['N000']}"
        (labelled.groupBy("model_version", "label").count().orderBy("label").show())
        print("All tests passed!")
    finally:
        service.stop()
        spark.stop()
        shutil.rmtree(work_dir, ignore_errors=True)
