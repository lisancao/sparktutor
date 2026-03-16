"""
Monitoring & Operations — Starter Code

Extract metrics from progress and detect anomalies.
"""

from pyspark.sql import SparkSession
from types import SimpleNamespace


def collect_batch_metrics(progress):
    """Extract batch_id, rows_processed, duration_ms from progress.
    progress has: batchId, numInputRows, batchDuration (as int, ms)."""
    return None


def alert_on_anomaly(metric_dicts):
    """Return True if duration > 60000 ms or 2+ consecutive batches with 0 rows."""
    return None


if __name__ == "__main__":
    progress1 = SimpleNamespace(batchId=0, numInputRows=1000, batchDuration=5000)
    progress2 = SimpleNamespace(batchId=1, numInputRows=0, batchDuration=1000)
    progress3 = SimpleNamespace(batchId=2, numInputRows=0, batchDuration=1000)
    progress4 = SimpleNamespace(batchId=3, numInputRows=500, batchDuration=70000)

    m1 = collect_batch_metrics(progress1)
    assert m1 is not None
    assert m1.get("batch_id") == 0
    assert m1.get("rows_processed") == 1000
    assert m1.get("duration_ms") == 5000
    assert m1.get("is_healthy") is True

    assert alert_on_anomaly([m1, collect_batch_metrics(progress2), collect_batch_metrics(progress3)]) is True
    assert alert_on_anomaly([m1, collect_batch_metrics(progress4)]) is True
    assert alert_on_anomaly([m1]) is False

    print("All tests passed!")
