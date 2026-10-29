"""
Running a Model over Your Data with pandas UDFs - Exercise

Train a tiny naive Bayes classifier on the driver, then label every policy
document, support e-mail and inbox ticket with it: a Series to Series pandas
UDF, an iterator pandas UDF that loads the model once per task, and
mapInPandas for batch scoring.
"""

import json
import math
import os
import re
import uuid
from collections import Counter
from typing import Iterator

import numpy as np
import pandas as pd
from pyspark import TaskContext
from pyspark.sql import SparkSession, functions as F

DOCS = "data/messy/docs/*.md"
MAIL = "data/messy/mail/*.eml"
TICKETS = "data/messy/support_tickets"
INBOX_SCHEMA = "ticket_id string, channel string, text string"
RESULT_TYPE = "struct<label:string, confidence:double>"
SCORE_SCHEMA = "id string, label string, confidence double"


# ---- The model: plain Python and NumPy, no Spark (given) ----

STOP_WORDS = {"a", "an", "and", "are", "be", "can", "do", "does", "for", "has", "have", "how",
              "i", "in", "is", "it", "me", "my", "no", "not", "of", "on", "or", "please",
              "still", "the", "this", "to", "we", "will", "with", "you", "your", "after"}
WORD = re.compile(r"[a-z]+")


def tokenize(text):
    """Lowercase words of two letters or more, without stop words. None gives []."""
    if text is None:
        return []
    return [w for w in WORD.findall(text.lower()) if len(w) > 1 and w not in STOP_WORDS]


def train_naive_bayes(rows, alpha=1.0):
    """Multinomial naive Bayes with add-one smoothing. rows: (text, label) pairs."""
    labels = sorted({label for _, label in rows})
    counts = {label: Counter() for label in labels}
    docs = Counter()
    for text, label in rows:
        docs[label] += 1
        counts[label].update(tokenize(text))
    vocab = sorted(set().union(*counts.values()))
    log_like = []
    for label in labels:
        total = sum(counts[label].values()) + alpha * len(vocab)
        log_like.append([math.log((counts[label][w] + alpha) / total) for w in vocab])
    log_prior = [math.log(docs[label] / len(rows)) for label in labels]
    return {"labels": labels, "vocab": vocab, "log_like": log_like, "log_prior": log_prior}


def predict_one(model, text):
    """(label, confidence) for one text; ("unknown", 0.0) when no word is in the vocabulary."""
    index = {w: i for i, w in enumerate(model["vocab"])}
    ids = [index[w] for w in tokenize(text) if w in index]
    if not ids:
        return ("unknown", 0.0)
    scores = [p + sum(row[i] for i in ids) for p, row in zip(model["log_prior"], model["log_like"])]
    best = max(range(len(scores)), key=lambda k: scores[k])
    return (model["labels"][best], 1.0 / sum(math.exp(s - scores[best]) for s in scores))


def predict_batch(model, texts):
    """Vectorized predict_one: a word-count matrix times the log-likelihood matrix.

    texts is a list (or pandas Series) of strings or None. Returns (labels, confidences)
    as two lists of the same length.
    """
    index = {w: i for i, w in enumerate(model["vocab"])}
    counts = np.zeros((len(texts), len(index)))
    for r, text in enumerate(texts):
        for w in tokenize(text):
            i = index.get(w)
            if i is not None:
                counts[r, i] += 1
    scores = counts @ np.asarray(model["log_like"]).T + np.asarray(model["log_prior"])
    best = scores.argmax(axis=1)
    confidence = 1.0 / np.exp(scores - scores.max(axis=1, keepdims=True)).sum(axis=1)
    known = counts.sum(axis=1) > 0
    labels = np.where(known, np.asarray(model["labels"], dtype=object)[best], "unknown")
    return labels.tolist(), np.where(known, confidence, 0.0).tolist()


def save_model(model, path):
    with open(path, "w") as f:
        json.dump(model, f)


def load_model(path):
    with open(path) as f:
        return json.load(f)


def record_load(marker_dir):
    """Leave one empty marker file per model load, named after the task that loaded it."""
    tc = TaskContext.get()
    part = tc.partitionId() if tc is not None else "driver"
    attempt = tc.attemptNumber() if tc is not None else 0
    name = f"load-p{part}-a{attempt}-pid{os.getpid()}-{uuid.uuid4().hex[:8]}"
    open(os.path.join(marker_dir, name), "w").close()


def load_model_for_task(model_path, marker_dir):
    """Load the model from its file, leaving a marker so the harness can count loads."""
    record_load(marker_dir)
    return load_model(model_path)


# ---- Your code ----

def load_texts(spark):
    """Every text to classify, as id, source, text.

    - source "doc": one row per policy file in DOCS; id is the file name, text the whole file
    - source "mail": one row per e-mail in MAIL; id is the file name, text is the
      Subject header, a space, then the body (everything after the first blank line)
    - source "inbox": one row per ticket in the inbox JSON Lines files; id is ticket_id
    """
    # TODO: read DOCS with text(..., wholetext=True) and take the id from _metadata.file_name
    # TODO: read MAIL the same way; build text with concat_ws(" ", <subject>, <body>) using
    #       regexp_extract with r"(?m)^Subject: (.*)$" and r"\r?\n\r?\n(.*)" (trim the body)
    # TODO: read the inbox with spark.read.schema(INBOX_SCHEMA).json(f"{TICKETS}/inbox")
    # TODO: give all three the columns id, source, text and combine them with unionByName
    return None


def train_on_driver(spark):
    """Read the labelled tickets with Spark, bring them to the driver, train the model."""
    # TODO: read f"{TICKETS}/train.csv" (it has a header), collect text and label,
    #       and return train_naive_bayes([(text, label), ...])
    return None


def label_column(texts, model):
    """Add a string column `label` with a Series -> Series pandas UDF.

    The model is small, so the UDF can capture it in its closure.
    """
    # TODO: define a @F.pandas_udf("string") function (text: pd.Series) -> pd.Series that
    #       calls predict_batch(model, text.tolist()) and returns the labels as a pd.Series
    # TODO: return texts with the new column `label`
    return None


def label_once_per_task(texts, model_path, marker_dir):
    """Add `label` and `confidence` with an iterator pandas UDF.

    Load the model with load_model_for_task(model_path, marker_dir) exactly once per
    task, before the loop over batches. The UDF returns RESULT_TYPE: a struct,
    built from a pandas DataFrame with columns label and confidence.
    """
    # TODO: define a @F.pandas_udf(RESULT_TYPE) function with the type hints
    #       (batches: Iterator[pd.Series]) -> Iterator[pd.DataFrame]
    #       - load the model once, at the top
    #       - for each batch, yield pd.DataFrame({"label": ..., "confidence": ...})
    # TODO: return the columns id, source, text, label, confidence
    return None


def score_partitions(texts, model_path, marker_dir):
    """Score with mapInPandas: one row per input row with SCORE_SCHEMA columns.

    Load the model once per partition, as in label_once_per_task.
    """
    # TODO: write a function that takes an iterator of pandas DataFrames (columns id, text),
    #       loads the model once, and yields DataFrames with columns id, label, confidence
    # TODO: return texts.select("id", "text").mapInPandas(<your function>, SCORE_SCHEMA)
    return None


def inbox_accuracy(scored, spark):
    """Fraction of inbox tickets whose predicted label matches inbox_labels.csv.

    scored has columns id and label (other columns are ignored). Return a float.
    """
    # TODO: read f"{TICKETS}/inbox_labels.csv" (header: ticket_id, label), join it to
    #       scored on the ticket id, and average (label == expected) as a double
    return None


# ---- Test harness ----
if __name__ == "__main__":
    import contextlib
    import io
    import shutil
    import tempfile

    spark = (SparkSession.builder
        .appName("InferenceWithPandasUDFs")
        .master("local[*]")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    work = tempfile.mkdtemp()

    def fresh_markers(name):
        path = os.path.join(work, name)
        shutil.rmtree(path, ignore_errors=True)
        os.makedirs(path)
        return path

    def loads(path):
        return sorted(os.listdir(path))

    def plan_of(df):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            df.explain()
        return buf.getvalue()

    try:
        texts = load_texts(spark)
        assert texts is not None, "load_texts returned None"
        assert texts.columns == ["id", "source", "text"], (
            f"Expected columns id, source, text; got {texts.columns}")
        rows = texts.collect()
        by_source = Counter(r.source for r in rows)
        assert by_source == {"doc": 4, "mail": 4, "inbox": 240}, (
            f"Expected 4 docs, 4 mails and 240 inbox tickets, got {dict(by_source)}")
        text_of = {r.id: r.text for r in rows}
        assert text_of.get("ticket_2.eml") == "Where is my order? Hello, order 1002 has a problem. Please help.", (
            f"ticket_2.eml should be 'Subject body', got {text_of.get('ticket_2.eml')!r}")
        assert text_of.get("shipping.md", "").startswith("# Shipping policy"), (
            "Each policy file should be one row with the whole file as text (wholetext=True)")
        assert text_of.get("I0024", "missing") is None, (
            "Ticket I0024 has \"text\": null in the JSON; keep it as a NULL text")

        model = train_on_driver(spark)
        assert model is not None, "train_on_driver returned None"
        assert model["labels"] == ["privacy", "returns", "shipping", "warranty"], (
            f"Expected four labels from train.csv, got {model.get('labels')}")
        assert predict_one(model, "my parcel never arrived, where is it?")[0] == "shipping", (
            "The model should label a parcel question as shipping; train on every row of train.csv")
        expected = {r.id: predict_one(model, r.text) for r in rows}

        # 1. Series -> Series pandas UDF, model in the closure
        labeled = label_column(texts, model)
        assert labeled is not None, "label_column returned None"
        assert "label" in labeled.columns, f"label_column should add a label column, got {labeled.columns}"
        plan = plan_of(labeled)
        assert "ArrowEvalPython" in plan and ", 200" in plan, (
            "label_column should use a pandas_udf (ArrowEvalPython with eval type 200 in explain())")
        got = {r.id: r.label for r in labeled.select("id", "label").collect()}
        wrong = [k for k in expected if got.get(k) != expected[k][0]]
        assert not wrong, (
            f"{len(wrong)} labels differ from predict_one, for example {wrong[0]}: "
            f"expected {expected[wrong[0]][0]}, got {got.get(wrong[0])}")

        # 2. Iterator pandas UDF: one model load per task, several batches per task
        model_path = os.path.join(work, "model.json")
        save_model(model, model_path)
        spark.conf.set("spark.sql.execution.arrow.maxRecordsPerBatch", "25")
        parts = texts.repartition(4)
        markers = fresh_markers("iterator")
        out = label_once_per_task(parts, model_path, markers)
        assert out is not None, "label_once_per_task returned None"
        assert out.columns == ["id", "source", "text", "label", "confidence"], (
            f"Expected columns id, source, text, label, confidence; got {out.columns}")
        result = out.collect()
        found = loads(markers)
        assert len(result) == 248, f"Expected 248 rows, got {len(result)}"
        assert len(found) == 4, (
            f"The model was loaded {len(found)} times for 4 tasks of about 62 rows in batches of 25. "
            "Call load_model_for_task once, before the for loop over batches, not inside it"
            if len(found) > 4 else
            f"The model was loaded {len(found)} times; call load_model_for_task once per task")
        assert sorted(f.split("-")[1] for f in found) == ["p0", "p1", "p2", "p3"], (
            f"Expected one load in each of the 4 partitions, got {found}")
        for r in result:
            label, conf = expected[r.id]
            assert r.label == label, f"{r.id}: expected label {label}, got {r.label}"
            assert r.confidence is not None and abs(r.confidence - conf) < 1e-9, (
                f"{r.id}: expected confidence {conf:.6f}, got {r.confidence}")

        # 3. mapInPandas: same predictions, one load per partition
        markers = fresh_markers("map")
        scored = score_partitions(parts, model_path, markers)
        assert scored is not None, "score_partitions returned None"
        assert scored.columns == ["id", "label", "confidence"], (
            f"Expected columns id, label, confidence; got {scored.columns}")
        scored_rows = scored.collect()
        found = loads(markers)
        assert len(found) == 4, f"mapInPandas should load the model once per partition (4), got {len(found)}"
        assert {r.id: r.label for r in scored_rows} == {k: v[0] for k, v in expected.items()}, (
            "score_partitions labels differ from predict_one")

        # 4. How good is it?
        answer_key = {}
        with open(f"{TICKETS}/inbox_labels.csv") as f:
            next(f)
            for line in f:
                tid, label = line.strip().split(",")
                answer_key[tid] = label
        want = sum(expected[t][0] == label for t, label in answer_key.items()) / len(answer_key)
        acc = inbox_accuracy(scored, spark)
        assert acc is not None and abs(acc - want) < 1e-9, f"Expected inbox accuracy {want:.4f}, got {acc}"
        for doc in ["privacy", "returns", "shipping", "warranty"]:
            assert expected[f"{doc}.md"][0] == doc, f"{doc}.md should be labelled {doc}"
        unknown = [k for k, v in expected.items() if v[0] == "unknown"]

        print(f"Inbox accuracy: {acc:.4f} ({round(acc * 240)} of 240)")
        print(f"Tickets with no usable words (unknown): {len(unknown)}")
        print("Model loads in the iterator UDF:", loads(os.path.join(work, "iterator")))
        (out.filter("source != 'inbox'").select("id", "label", F.round("confidence", 3).alias("confidence"))
            .orderBy("id").show(truncate=False))
        print("All tests passed!")
    finally:
        spark.stop()
        shutil.rmtree(work, ignore_errors=True)
