"""
Reading from an API - Exercise

A Python data source that pages through a REST API in parallel: one partition
per page, network calls only in read(), retries for flaky pages, and the loose
part of each record returned as VARIANT.

The API is a small standard-library HTTP server started by the harness, so the
exercise needs no internet connection.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from pyspark.sql import SparkSession, functions as sf
from pyspark.sql.datasource import DataSource, DataSourceReader, InputPartition


# ---- The API (already written) -------------------------------------------
# GET /tickets?page=N&page_size=M returns
#   {"items": [...], "page": N, "page_size": M, "total": 95}
# Each item: {"id": int, "status": str, "subject": str, "meta": {...}} where
# meta always has "tags" and only sometimes "priority" or "customer".
# Page 3 is flaky: every other request to it gets an HTTP 503.

TAGS = [[], ["shipping"], ["refund", "urgent"], ["shipping", "damaged"]]
SUBJECTS = ["Where is my order?", "Refund request", "Broken item"]


def make_tickets(total=95):
    tickets = []
    for i in range(total):
        meta = {"tags": TAGS[i % 4]}
        if i % 5 == 0:
            meta["priority"] = "high"
        if i % 7 == 0:
            meta["customer"] = {"id": f"C{i % 4}", "tier": "gold"}
        tickets.append({"id": i, "status": ["open", "closed", "pending"][i % 3],
                        "subject": SUBJECTS[i % 3], "meta": meta})
    return tickets


def start_api():
    """Serve the tickets on 127.0.0.1 and a free port; return (server, base_url, request_log)."""
    tickets = make_tickets()
    log = []
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            page = int(q.get("page", ["0"])[0])
            size = int(q.get("page_size", ["20"])[0])
            with lock:
                log.append(page)
                if page == 3:
                    server.page3_requests += 1
                flaky = page == 3 and server.page3_requests % 2 == 1
            if url.path != "/tickets":
                self.send_error(404)
                return
            if flaky:
                self.send_error(503, "try again")
                return
            body = json.dumps({"items": tickets[page * size:(page + 1) * size], "page": page,
                               "page_size": size, "total": len(tickets)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.page3_requests = 0
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/tickets", log


# ---- The data source ------------------------------------------------------

def fetch_json(url, timeout, retries):
    """GET url and parse the JSON body, retrying server errors (5xx) and network errors.

    Waits 0.1 s, 0.2 s, 0.4 s, ... between attempts and raises the last error
    when `retries` retries are used up. Client errors (4xx) are raised at once.
    """
    import json
    import time
    from urllib.error import HTTPError, URLError
    from urllib.request import urlopen

    # TODO: loop over attempts 0..retries:
    #   - urlopen(url, timeout=timeout) inside a with block, return json.load(response)
    #   - on HTTPError: raise at once if e.code < 500 or this was the last attempt
    #   - on URLError (network error): raise if this was the last attempt
    #   - otherwise time.sleep(0.1 * 2 ** attempt) and try again
    raise NotImplementedError("fetch_json is not written yet")


class PagePartition(InputPartition):
    def __init__(self, page):
        self.page = page


class TicketsDataSource(DataSource):
    """format("tickets"): options url (required), page_size (20), timeout (10 s), retries (3)."""

    def __init__(self, options):
        super().__init__(options)
        # TODO: raise ValueError("option 'url' is required") when the option is missing

    @classmethod
    def name(cls):
        return "tickets"

    def schema(self):
        return "id int, status string, subject string, meta variant"

    def reader(self, schema):
        return TicketsReader(self.options)


class TicketsReader(DataSourceReader):
    def __init__(self, options):
        self.url = options["url"]
        self.page_size = int(options.get("page_size", 20))
        self.timeout = float(options.get("timeout", 10))
        self.retries = int(options.get("retries", 3))

    def page_url(self, page):
        return f"{self.url}?page={page}&page_size={self.page_size}"

    def partitions(self):
        # Runs once, before any task: ask for the first page to learn the total.
        # TODO: fetch page 0 with fetch_json, compute the number of pages from
        #   "total" and self.page_size (math.ceil), return one PagePartition per page
        return [PagePartition(0)]

    def read(self, partition):
        # Runs in a task, one call per page, in parallel with the other pages.
        import json
        from pyspark.sql.types import VariantVal

        # TODO: fetch this partition's page with fetch_json and yield one tuple
        #   per item: (id, status, subject, meta) where meta is
        #   VariantVal.parseJson(json.dumps(item["meta"]))
        return iter([])


# ---- Test harness ----
if __name__ == "__main__":
    import time
    from collections import Counter

    spark = (SparkSession.builder
        .appName("ApiSource")
        .master("local[*]")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    server, url, requests = start_api()
    expected = make_tickets()

    def settle():
        time.sleep(0.2)  # let the server threads finish logging

    try:
        spark.dataSource.register(TicketsDataSource)

        # 1. A missing option fails as soon as the plan is analyzed, not halfway through a job
        #    (.columns forces analysis on Spark Connect too, where load() is lazy)
        try:
            spark.read.format("tickets").load().columns
            raise AssertionError("load() without the url option should fail: check it in TicketsDataSource.__init__")
        except AssertionError:
            raise
        except Exception as e:
            assert "option 'url' is required" in str(e), (
                f"Expected the message \"option 'url' is required\", got {str(e)[:300]}")

        # 2. One partition per page, every ticket once
        df = (spark.read.format("tickets").option("url", url)
            .option("page_size", 20).option("retries", 2).load())
        assert dict(df.dtypes)["meta"] == "variant", f"meta should be VARIANT, got {df.dtypes}"
        rows = df.collect()
        ids = sorted(r.id for r in rows)
        assert ids == list(range(95)), (
            f"Expected ids 0 to 94 once each, got {len(ids)} rows: {ids[:12]}... "
            "Plan one partition per page and read each page in read()")
        n_parts = df.select(sf.spark_partition_id().alias("p")).distinct().count()
        assert n_parts == 5, f"95 tickets at 20 per page should be 5 partitions, got {n_parts}"
        settle()
        assert requests.count(3) >= 2, (
            "Page 3 answers 503 every other time, so it needs a retry; fetch_json should retry 5xx errors")

        # 3. The loose part, through VARIANT
        status = {r.status: r["count"] for r in df.groupBy("status").count().collect()}
        assert status == dict(Counter(t["status"] for t in expected)), f"Unexpected status counts {status}"
        tags = {r.tag: r["count"] for r in df.select(
            sf.explode(sf.try_variant_get("meta", "$.tags", "array<string>")).alias("tag"))
            .groupBy("tag").count().collect()}
        assert tags == dict(Counter(t for x in expected for t in x["meta"]["tags"])), f"Unexpected tag counts {tags}"
        high = df.filter(sf.try_variant_get("meta", "$.priority", "string") == "high").count()
        assert high == sum(1 for t in expected if "priority" in t["meta"]), f"Unexpected high-priority count {high}"
        gold = df.filter(sf.try_variant_get("meta", "$.customer.tier", "string") == "gold").count()
        assert gold == sum(1 for t in expected if "customer" in t["meta"]), f"Unexpected gold-customer count {gold}"

        # 4. page_size is an option: 50 per page means 2 partitions
        big = spark.read.format("tickets").option("url", url).option("page_size", 50).load()
        assert big.count() == 95, "page_size 50 should still return 95 tickets"
        assert big.select(sf.spark_partition_id()).distinct().count() == 2, "page_size 50 should give 2 partitions"

        # 5. Without retries the flaky page fails the job
        settle()
        server.page3_requests = 0  # the next request to page 3 gets a 503
        try:
            spark.read.format("tickets").option("url", url).option("retries", 0).load().count()
            raise AssertionError("With retries=0 the 503 from page 3 should fail the read")
        except AssertionError:
            raise
        except Exception as e:
            assert "503" in str(e), f"Expected the HTTP 503 in the error, got {str(e)[:300]}"

        # 6. Every action calls the API again, unless you cache
        settle()
        requests.clear()
        df.count()
        settle()
        per_action = len(requests)
        df.cache().count()
        settle()
        requests.clear()
        df.groupBy("status").count().collect()
        settle()
        assert requests == [], f"A query on the cached DataFrame should not call the API, got {requests}"

        print(f"API: {url}")
        print(f"API requests made by one uncached action: {per_action}; by an action on the cache: 0")
        df.groupBy("status").agg(sf.count("*").alias("n")).orderBy("status").show()
        df.select("id", "subject", "meta").orderBy("id").show(5, truncate=False)
        print("All tests passed!")
    finally:
        spark.stop()
        server.shutdown()
