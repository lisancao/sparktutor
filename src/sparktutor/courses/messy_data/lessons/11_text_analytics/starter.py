"""
Text Analytics Without an LLM - Exercise

Count words, build a TF-IDF search index over the policy documents, and find
near-duplicate support messages with MinHash, all with Spark MLlib.
"""

from pyspark.ml import Pipeline
from pyspark.ml.feature import (
    HashingTF, IDF, MinHashLSH, Normalizer, RegexTokenizer, StopWordsRemover,
)
from pyspark.sql import SparkSession, functions as sf

DOCS = "data/messy/docs/*.md"
MAIL = "data/messy/mail/*.eml"

# Chat messages that arrived through another channel
CHATS = [
    ("chat_0", "Where is my order 1042? It has not arrived yet."),
    ("chat_1", "Where is my order 1042?? It has not arrived yet!"),
    ("chat_2", "Do you ship express to Vietnam?"),
]


def load_docs(spark):
    """One row per Markdown file: doc (the file name) and text (the whole file)."""
    # TODO: spark.read.text(DOCS, wholetext=True), then select
    #   _metadata.file_name as doc and value as text
    return None


def words_stage():
    """Tokenizer and stop word remover shared by the word count and the index."""
    return [
        RegexTokenizer(inputCol="text", outputCol="tokens", pattern=r"[^a-zA-Z]+"),
        StopWordsRemover(inputCol="tokens", outputCol="words"),
    ]


def top_words(docs, n):
    """The n most frequent words over all documents, without stop words: (word, count)."""
    tokens, remover = words_stage()
    # TODO: transform docs with both stages, explode the words column into
    #   a column named word, count per word, order by count descending then
    #   word, and keep the first n rows
    return None


def fit_search_index(docs):
    """Fit tokens -> words -> term frequencies -> TF-IDF -> unit-length vector `vec`."""
    # TODO: a Pipeline of words_stage() plus HashingTF (words -> tf, 4096
    #   features), IDF (tf -> tfidf) and Normalizer (tfidf -> vec, p=2.0);
    #   return pipeline.fit(docs)
    return None


def search(model, docs, query):
    """Rank every document against `query` by cosine similarity: (doc, score), best first."""
    spark = docs.sparkSession
    # TODO: transform docs with the model; transform a one-row DataFrame
    #   holding the query (column text) and keep its vec as q; cross join,
    #   score with a UDF that returns float(a.dot(b)), order by score desc, doc
    return None


def load_messages(spark):
    """Support e-mail bodies (id = file name without .eml) plus the chat messages."""
    # TODO: read MAIL with wholetext=True; id = the file name without .eml
    #   (regexp_extract on _metadata.file_name), text = everything after the
    #   first blank line, trimmed. Union with CHATS (id string, text string).
    return None


def near_duplicates(messages, threshold):
    """Pairs of messages whose word sets have a Jaccard distance below threshold: (a, b, distance), a < b."""
    # TODO: RegexTokenizer (pattern \W+) -> HashingTF (1024 features,
    #   binary=True) -> fit MinHashLSH (numHashTables=5, seed=7) ->
    #   approxSimilarityJoin(features, features, threshold), keep pairs with
    #   datasetA.id < datasetB.id and select a, b and distCol as distance
    return None


# ---- Test harness ----
if __name__ == "__main__":
    import glob
    import re
    from collections import Counter

    spark = (SparkSession.builder
        .appName("TextAnalytics")
        .master("local[*]")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    try:
        docs = load_docs(spark)
        assert docs is not None, "load_docs returned None"
        assert docs.columns == ["doc", "text"], f"Expected columns doc, text; got {docs.columns}"
        names = sorted(r.doc for r in docs.collect())
        assert names == ["privacy.md", "returns.md", "shipping.md", "warranty.md"], (
            f"Expected one row per .md file, got {names}: read with text(..., wholetext=True)")

        # Expected word counts, computed with plain Python and Spark's English stop words
        stop = set(StopWordsRemover.loadDefaultStopWords("english"))
        counts = Counter()
        for path in glob.glob(DOCS):
            counts.update(w for w in re.split(r"[^a-zA-Z]+", open(path).read().lower()) if w and w not in stop)
        expected = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]

        top = top_words(docs, 5)
        assert top is not None, "top_words returned None"
        got = [(r[0], r[1]) for r in top.collect()]
        assert got == expected, f"Expected top words {expected}, got {got}"

        model = fit_search_index(docs)
        assert model is not None, "fit_search_index returned None"
        for query, best in [("how long does express shipping take", "shipping.md"),
                            ("can I return an unopened item for a refund", "returns.md"),
                            ("battery warranty", "warranty.md")]:
            ranked = search(model, docs, query)
            assert ranked is not None, "search returned None"
            rows = [(r.doc, r.score) for r in ranked.collect()]
            assert len(rows) == 4, f"search should score every document, got {rows}"
            assert rows[0][0] == best and rows[0][1] > 0, f"'{query}' should rank {best} first, got {rows}"
            assert all(abs(s) < 1e-9 for _, s in rows[1:]), (
                f"'{query}' shares no words with the other documents, so they should score 0, got {rows}")
            assert rows[0][1] <= 1.0 + 1e-9, (
                f"Cosine scores are at most 1; got {rows[0][1]}. Normalize the TF-IDF vectors (Normalizer)")
        nothing = search(model, docs, "pizza").collect()
        assert all(r.score == 0 for r in nothing), "A query with no known words should score 0 everywhere"

        messages = load_messages(spark)
        assert messages is not None, "load_messages returned None"
        texts = {r.id: r.text for r in messages.collect()}
        assert len(texts) == 7, f"Expected 4 e-mails and 3 chats, got {sorted(texts)}"
        assert texts.get("ticket_0") == "Hello, order 1000 has a problem. Please help.", (
            f"ticket_0 should be the e-mail body only, got {texts.get('ticket_0')!r}")

        dupes = near_duplicates(messages, 0.3)
        assert dupes is not None, "near_duplicates returned None"
        assert dupes.columns == ["a", "b", "distance"], f"Expected columns a, b, distance; got {dupes.columns}"
        found = {(r.a, r.b): round(r.distance, 4) for r in dupes.collect()}
        tickets = [f"ticket_{i}" for i in range(4)]
        expected_pairs = {("chat_0", "chat_1")} | {(x, y) for x in tickets for y in tickets if x < y}
        assert set(found) == expected_pairs, (
            f"Expected the chat pair and every pair of tickets, got {sorted(found)}")
        assert found[("chat_0", "chat_1")] == 0.0, "The two chats have the same words: distance 0"
        assert found[("ticket_0", "ticket_1")] == 0.2222, (
            "Two tickets share 7 of 9 distinct words, so their Jaccard distance is 2/9")
        strict = {(r.a, r.b) for r in near_duplicates(messages, 0.1).collect()}
        assert strict == {("chat_0", "chat_1")}, f"With threshold 0.1 only the chat pair is left, got {strict}"

        print("Top words:", got)
        search(model, docs, "how long does express shipping take").show()
        dupes.orderBy("a", "b").show()
        print("All tests passed!")
    finally:
        spark.stop()
