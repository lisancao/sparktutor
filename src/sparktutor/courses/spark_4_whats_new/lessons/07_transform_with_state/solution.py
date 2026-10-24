"""
transformWithState - Solution

A stateful spend tracker in Python: ValueState + ListState, initial state,
a named streaming source, the state reader, and a real-time mode probe.
"""

import json
import os
import tempfile

from pyspark.sql import SparkSession, Row, functions as sf
from pyspark.sql.streaming import StatefulProcessor, StatefulProcessorHandle
from pyspark.errors import PySparkException


OUTPUT_SCHEMA = "user string, total long, events int, flagged boolean"
LIMIT = 100


class SpendTracker(StatefulProcessor):
    """Running spend per user; flags users whose total crosses LIMIT."""

    def init(self, handle: StatefulProcessorHandle) -> None:
        self.total = handle.getValueState("total", "amount long")
        self.history = handle.getListState("history", "amount long")

    def handleInitialState(self, key, initialState, timerValues) -> None:
        # Called once per key in the first batch, before any input rows.
        self.total.update((initialState.opening_balance,))

    def handleInputRows(self, key, rows, timerValues):
        (user,) = key
        total = self.total.get()[0] if self.total.exists() else 0
        count = 0
        for r in rows:
            total += r.amount
            count += 1
            self.history.appendValue((r.amount,))
        self.total.update((total,))
        yield Row(user=user, total=total, events=count, flagged=total > LIMIT)

    def close(self) -> None:
        pass


def drop_file(directory, name, rows):
    with open(os.path.join(directory, f"{name}.json"), "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def run_spend_tracker(spark, workdir):
    """Run two micro-batches through transformWithState and inspect the state."""

    incoming = os.path.join(workdir, "incoming")
    checkpoint = os.path.join(workdir, "checkpoint")
    os.makedirs(incoming)

    # Opening balances, loaded once as initial state.
    opening = spark.createDataFrame(
        [("ann", 50), ("cat", 7)], "user string, opening_balance long"
    )

    # Source naming (4.2) is experimental and flag-gated. With the flag on,
    # every streaming source in the query must be named.
    spark.conf.set("spark.sql.streaming.queryEvolution.enableSourceEvolution", "true")
    events = (spark.readStream
              .schema("user string, amount long")
              .name("spend_events")
              .json(incoming))

    tracked = events.groupBy("user").transformWithState(
        statefulProcessor=SpendTracker(),
        outputStructType=OUTPUT_SCHEMA,
        outputMode="Update",
        timeMode="None",
        initialState=opening.groupBy("user"),
    )

    query = (tracked.writeStream
             .format("memory").queryName("spend")
             .outputMode("update")
             .option("checkpointLocation", checkpoint)
             .trigger(processingTime="1 second")
             .start())

    drop_file(incoming, "batch1", [
        {"user": "ann", "amount": 30}, {"user": "bob", "amount": 5}, {"user": "ann", "amount": 80},
    ])
    query.processAllAvailable()
    after_first = {r["user"]: r["total"] for r in spark.table("spend").collect()}

    drop_file(incoming, "batch2", [
        {"user": "bob", "amount": 200}, {"user": "cat", "amount": 1},
    ])
    query.processAllAvailable()
    query.stop()

    # The memory sink in update mode appends every emitted row; keep the latest.
    latest = spark.sql("""
        SELECT user, total, flagged FROM spend
        QUALIFY row_number() OVER (PARTITION BY user ORDER BY total DESC) = 1
        ORDER BY user
    """)

    # Read the operator's state straight from the checkpoint (state data source).
    state_totals = {
        r["key"]["user"]: r["value"]["amount"]
        for r in spark.read.format("statestore")
                     .option("stateVarName", "total")
                     .load(checkpoint)
                     .collect()
    }

    # Real-time mode trigger (PySpark API in 4.2). The rate source is not an
    # RTM source, so the query fails at start-up with a clear condition.
    # It needs a name too: the evolution flag is session-wide.
    rtm_error = None
    rtm = (spark.readStream.format("rate").name("rate_probe").load()
           .writeStream.format("console").outputMode("update")
           .trigger(realTime="5 seconds")
           .start())
    try:
        rtm.awaitTermination(60)
    except PySparkException as e:
        rtm_error = str(e)
    finally:
        rtm.stop()

    return {
        "after_first": after_first,
        "latest": latest,
        "state_totals": state_totals,
        "rtm_error": rtm_error,
    }


# ---- Test harness ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("TransformWithStateTest")
        .master("local[*]")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.streaming.stateStore.providerClass",
                "org.apache.spark.sql.execution.streaming.state.RocksDBStateStoreProvider")
        .getOrCreate())

    workdir = tempfile.mkdtemp(prefix="sparktutor_tws_")
    result = run_spend_tracker(spark, workdir)
    assert result is not None, "Function returned None"
    assert result["after_first"] == {"ann": 160, "bob": 5}, \
        f"Batch 1: ann = 50 opening + 110, cat has no input yet; got {result['after_first']}"
    latest = {r["user"]: (r["total"], r["flagged"]) for r in result["latest"].collect()}
    assert latest == {"ann": (160, True), "bob": (205, True), "cat": (8, False)}, latest
    assert result["state_totals"] == {"ann": 160, "bob": 205, "cat": 8}, result["state_totals"]
    assert result["rtm_error"] and "STREAMING_REAL_TIME_MODE.INPUT_STREAM_NOT_SUPPORTED" in result["rtm_error"], \
        f"Expected the RTM source check to fail, got: {result['rtm_error']}"
    result["latest"].show()
    print("State store totals:", result["state_totals"])
    print("RTM probe:", result["rtm_error"].splitlines()[0][:160])
    print("All tests passed!")
    spark.stop()
