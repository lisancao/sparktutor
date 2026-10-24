"""
transformWithState - Starter Code

Complete `SpendTracker` and `run_spend_tracker(spark, workdir)`:
1. init(): ValueState "total" and ListState "history", both "amount long"
2. handleInitialState(): seed total from initialState.opening_balance
3. handleInputRows(): add the batch's amounts to total, append each amount
   to history, update total, and yield
   Row(user=..., total=..., events=<rows this batch>, flagged=total > LIMIT)
4. run_spend_tracker(): enable source evolution, name the file source
   "spend_events", call transformWithState with initialState, stream into
   the memory sink "spend", processAllAvailable() after each file
5. Read the "total" state variable with the statestore reader, and probe
   real-time mode on a (named) rate source, capturing the error text
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
        # TODO: self.total = handle.getValueState(...)
        # TODO: self.history = handle.getListState(...)
        pass

    def handleInitialState(self, key, initialState, timerValues) -> None:
        # TODO: self.total.update((initialState.opening_balance,))
        pass

    def handleInputRows(self, key, rows, timerValues):
        (user,) = key
        # TODO: read the current total (0 if it does not exist), add each
        #       r.amount, append it to history, count rows, update total
        total, count = 0, 0
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

    opening = spark.createDataFrame(
        [("ann", 50), ("cat", 7)], "user string, opening_balance long"
    )

    # TODO: spark.conf.set("spark.sql.streaming.queryEvolution.enableSourceEvolution", "true")
    # TODO: events = spark.readStream.schema("user string, amount long").name("spend_events").json(incoming)
    events = None  # Replace

    # TODO: events.groupBy("user").transformWithState(statefulProcessor=..., outputStructType=OUTPUT_SCHEMA,
    #       outputMode="Update", timeMode="None", initialState=opening.groupBy("user"))
    tracked = None  # Replace

    # TODO: memory sink "spend", outputMode("update"), checkpointLocation, processingTime="1 second"
    query = None  # Replace

    drop_file(incoming, "batch1", [
        {"user": "ann", "amount": 30}, {"user": "bob", "amount": 5}, {"user": "ann", "amount": 80},
    ])
    # TODO: query.processAllAvailable()
    after_first = {r["user"]: r["total"] for r in spark.table("spend").collect()}

    drop_file(incoming, "batch2", [
        {"user": "bob", "amount": 200}, {"user": "cat", "amount": 1},
    ])
    # TODO: query.processAllAvailable(); query.stop()

    # The memory sink in update mode appends every emitted row; keep the latest.
    latest = spark.sql("""
        SELECT user, total, flagged FROM spend
        QUALIFY row_number() OVER (PARTITION BY user ORDER BY total DESC) = 1
        ORDER BY user
    """)

    # TODO: {key.user: value.amount} from spark.read.format("statestore")
    #       .option("stateVarName", "total").load(checkpoint)
    state_totals = None  # Replace

    # TODO: rate source (named "rate_probe") -> console, outputMode("update"),
    #       trigger(realTime="5 seconds"); awaitTermination(60) inside try,
    #       store str(e) of the PySparkException in rtm_error; stop() in finally
    rtm_error = None

    return {
        "after_first": after_first,
        "latest": latest,
        "state_totals": state_totals,
        "rtm_error": rtm_error,
    }


# ---- Test harness (do not modify below this line) ----
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
