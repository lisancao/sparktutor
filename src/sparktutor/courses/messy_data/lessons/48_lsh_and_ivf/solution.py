"""
Building LSH and an IVF Vector Index - Solution

MinHash signatures and banding for near-duplicate listings, built from
Spark's higher-order functions (no UDFs), and an IVF index over vectors:
assign every vector to its nearest centroid, then search only the nprobe
nearest lists. The harness measures both against exact answers: recall of
the true pairs and neighbours, and how much work the index saved.
"""

import random

import numpy as np
from pyspark.ml.clustering import KMeans
from pyspark.ml.functions import array_to_vector
from pyspark.sql import SparkSession, functions as F

P = 2147483647          # 2^31 - 1, a Mersenne prime: (a * x + b) stays below 2^62
SHINGLE = 5             # characters per shingle

# Physical nodes that run Python (a correct answer uses none of them)
PYTHON_NODES = ("ArrowEvalPython", "BatchEvalPython", "MapInPandas", "MapInArrow")


# ---------------------------------------------------------------------------
# Given: text to hashed shingles
# ---------------------------------------------------------------------------

def shingles(listings):
    """(listing_id, h): the distinct character 5-shingles of the normalized
    description, each hashed to an integer in [0, P). Text shorter than one
    shingle becomes a single shingle (never an empty set)."""
    text = F.trim(F.regexp_replace(F.lower("description"), r"[^a-z0-9]+", " "))
    grams = F.when(F.length(text) < SHINGLE, F.array(text)).otherwise(
        F.transform(F.sequence(F.lit(1), F.length(text) - SHINGLE + 1),
                    lambda i: F.substring(text, i, SHINGLE)))
    return listings.select(
        "listing_id",
        F.transform(F.array_distinct(grams), lambda s: F.pmod(F.xxhash64(s), F.lit(P))).alias("h"))


def hash_params(k, seed=7):
    """k pairs (a, b) for the hash functions h(x) = (a * x + b) mod P."""
    rng = random.Random(seed)
    return [(rng.randrange(1, P), rng.randrange(0, P)) for _ in range(k)]


# ---------------------------------------------------------------------------
# Part 1: MinHash and banding
# ---------------------------------------------------------------------------

def minhash(sh, params):
    """Add `sig`: for each (a, b) in params, the minimum over the shingle
    hashes x of (a * x + b) % P. Built-in functions only: no UDF, no explode,
    no shuffle."""
    coeffs = F.array(*[F.struct(F.lit(a).cast("bigint").alias("a"),
                                F.lit(b).cast("bigint").alias("b")) for a, b in params])
    sig = F.transform(coeffs, lambda c: F.array_min(
        F.transform("h", lambda x: (c["a"] * x + c["b"]) % P)))
    return sh.withColumn("sig", sig)


def candidate_probability(s, b, r):
    """Probability that a pair with Jaccard similarity s shares at least one
    of b bands of r rows."""
    return 1 - (1 - s ** r) ** b


def choose_bands(k, threshold, min_prob):
    """The (b, r) with b * r == k and the largest r such that a pair at the
    threshold becomes a candidate with probability >= min_prob."""
    best = None
    for r in range(1, k + 1):
        if k % r == 0 and candidate_probability(threshold, k // r, r) >= min_prob:
            best = (k // r, r)
    return best


def candidate_pairs(sig, b, r):
    """Distinct (a, b) listing pairs, a < b, that share the bucket of at
    least one band. A band's bucket is xxhash64 of its r signature values."""
    bands = sig.select(
        "listing_id",
        F.posexplode(F.transform(F.sequence(F.lit(0), F.lit(b - 1)),
                                 lambda i: F.xxhash64(F.slice("sig", i * r + 1, r))))
        .alias("band", "bucket"))
    x, y = bands.alias("x"), bands.alias("y")
    return (x.join(y, (F.col("x.band") == F.col("y.band"))
                   & (F.col("x.bucket") == F.col("y.bucket"))
                   & (F.col("x.listing_id") < F.col("y.listing_id")))
            .select(F.col("x.listing_id").alias("a"), F.col("y.listing_id").alias("b"))
            .distinct())


def verify(cands, sh, threshold):
    """Keep the candidate pairs whose exact Jaccard similarity is at least
    threshold, with that similarity as `j`."""
    ha = sh.select(F.col("listing_id").alias("a"), F.col("h").alias("ha"))
    hb = sh.select(F.col("listing_id").alias("b"), F.col("h").alias("hb"))
    j = F.size(F.array_intersect("ha", "hb")) / F.size(F.array_union("ha", "hb"))
    return (cands.join(ha, "a").join(hb, "b")
            .select("a", "b", j.alias("j"))
            .filter(F.col("j") >= threshold))


# ---------------------------------------------------------------------------
# Part 2: an IVF index
# ---------------------------------------------------------------------------

def sqdist(u, v):
    """Squared Euclidean distance of two array<double> columns."""
    return F.aggregate(F.zip_with(u, v, lambda x, y: (x - y) * (x - y)),
                       F.lit(0.0), lambda acc, z: acc + z)


def centroid_array(centroids):
    """The centroids as one literal array<array<double>> column."""
    return F.array(*[F.array(*[F.lit(float(x)) for x in c]) for c in centroids])


def assign_lists(vectors, centroids):
    """Add `list`: the 0-based index of the nearest centroid to `v`."""
    d = F.transform(centroid_array(centroids), lambda c: sqdist(F.col("v"), c))
    return vectors.withColumn("list", F.array_position(d, F.array_min(d)) - 1)


def ivf_candidates(queries, index, centroids, nprobe):
    """(qid, id, dist) for every indexed vector in the nprobe lists whose
    centroids are nearest to each query `q`."""
    d = F.transform(centroid_array(centroids), lambda c: sqdist(F.col("q"), c))
    ranked = F.array_sort(F.arrays_zip(d.alias("d"),
                                       F.sequence(F.lit(0), F.lit(len(centroids) - 1)).alias("l")))
    probes = queries.select("qid", "q", F.explode(F.slice(ranked, 1, nprobe)).alias("p"))
    probes = probes.select("qid", "q", F.col("p.l").alias("list"))
    return (probes.join(index, "list")
            .select("qid", "id", sqdist(F.col("q"), F.col("v")).alias("dist")))


def top_k(scored, k):
    """(qid, ids): the ids of the k smallest distances per query, nearest
    first."""
    best = F.slice(F.array_sort(F.collect_list(F.struct("dist", "id"))), 1, k)
    return scored.groupBy("qid").agg(F.transform(best, lambda s: s["id"]).alias("ids"))


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

def plan_nodes(df):
    out, stack = [], [df._jdf.queryExecution().executedPlan()]
    while stack:
        node = stack.pop()
        out.append(node.nodeName())
        if node.nodeName() == "AdaptiveSparkPlan":
            stack.append(node.executedPlan())
            continue
        ch = node.children()
        stack.extend(ch.apply(i) for i in range(ch.length()))
    return out


def make_vectors(n, n_queries, dim=32, clusters=40, seed=48):
    """Clustered unit vectors standing in for embeddings. Cluster sizes
    follow a Zipf law, so some regions are much denser than others."""
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(clusters, dim))
    weights = rng.zipf(1.6, size=clusters).astype(float)
    labels = rng.choice(clusters, size=n + n_queries, p=weights / weights.sum())
    x = centers[labels] + rng.normal(scale=0.6, size=(n + n_queries, dim))
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    return x[:n], x[n:]


if __name__ == "__main__":
    spark = (SparkSession.builder.master("local[*]")
             .config("spark.sql.shuffle.partitions", "8")
             .config("spark.ui.showConsoleProgress", "false")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    # ---- Part 1: MinHash ----
    listings = spark.read.json("data/messy/listings/listings.jsonl")
    sh = shingles(listings).cache()
    n_docs = sh.count()
    all_pairs = n_docs * (n_docs - 1) // 2

    K, THRESHOLD = 100, 0.7
    params = hash_params(K)
    sig = minhash(sh, params)
    assert sig is not None, "minhash returned None. Return sh with a new `sig` column."
    sig = sig.cache()
    nodes = plan_nodes(sig.select("sig"))
    assert not [n for n in nodes if n in PYTHON_NODES], (
        f"minhash runs Python ({[n for n in nodes if n in PYTHON_NODES]}). Use F.transform "
        "and F.array_min, not a UDF.")
    assert "Exchange" not in nodes and "Generate" not in nodes, (
        "minhash should not explode or shuffle: every signature is computed from one row.")

    # Oracle: plain Python over the same shingle hashes
    rows = {r["listing_id"]: r for r in sig.collect()}
    sets = {lid: set(r["h"]) for lid, r in rows.items()}
    some = sorted(rows)[:5]
    for lid in some:
        expected = [min((a * x + b) % P for x in sets[lid]) for a, b in params]
        assert rows[lid]["sig"] == expected, (
            f"The signature of {lid} differs from min((a * x + b) % P) over its shingles. "
            f"First values: got {rows[lid]['sig'][:3]}, expected {expected[:3]}.")

    ids = sorted(sets)
    exact = {}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            inter = len(sets[a] & sets[b])
            if inter:
                exact[(a, b)] = inter / len(sets[a] | sets[b])
    errors = []
    for (a, b), j in exact.items():
        est = sum(x == y for x, y in zip(rows[a]["sig"], rows[b]["sig"])) / K
        errors.append(abs(est - j))
    mean_err = sum(errors) / len(errors)
    print(f"{n_docs} listings, {all_pairs} pairs, {len(exact)} share a shingle; "
          f"mean |MinHash estimate - Jaccard| over those = {mean_err:.4f}")
    assert mean_err < 0.05, (
        f"MinHash estimates are off by {mean_err:.3f} on average; with {K} hash functions "
        "they should be within about 0.03 of the exact Jaccard similarity.")
    print("minhash passes: signatures match, estimates track Jaccard, no Python, no shuffle")

    # ---- Part 1: choosing b and r ----
    choice = choose_bands(K, THRESHOLD, 0.99)
    assert choice is not None, "choose_bands returned None."
    print(f"choose_bands({K}, {THRESHOLD}, 0.99) = {choice}")
    assert choice == (25, 4), (
        f"choose_bands({K}, {THRESHOLD}, 0.99) returned {choice}. Check every divisor r of k "
        "with b = k // r and keep the largest r with 1 - (1 - t**r)**b >= min_prob.")
    assert choose_bands(K, 0.9, 0.99) == (20, 5), "choose_bands(100, 0.9, 0.99) should be (20, 5)."
    assert choose_bands(4, 0.1, 0.9) is None, (
        "choose_bands should return None when no divisor reaches min_prob.")
    b, r = choice

    # ---- Part 1: candidates and verification ----
    cands = candidate_pairs(sig, b, r)
    assert cands is not None, "candidate_pairs returned None."
    cands = cands.cache()
    n_cands = cands.count()
    pairs = {(row["a"], row["b"]) for row in cands.collect()}
    assert len(pairs) == n_cands, "candidate_pairs returns duplicate pairs; add distinct()."
    assert all(a < b_ for a, b_ in pairs), "Every candidate pair must have a < b."
    truth = {p for p, j in exact.items() if j >= THRESHOLD}
    recall = len(truth & pairs) / len(truth)
    print(f"b={b} r={r}: {n_cands} candidates ({n_cands / all_pairs:.2%} of all pairs), "
          f"recall of the {len(truth)} pairs with J >= {THRESHOLD}: {recall:.3f}")
    assert recall >= 0.99, (
        f"Only {recall:.1%} of the pairs with Jaccard >= {THRESHOLD} became candidates. "
        "Two listings are candidates when any band (r consecutive signature values) matches.")
    assert n_cands <= 0.05 * all_pairs, (
        f"{n_cands} candidates is more than 5% of all {all_pairs} pairs: the index saves "
        "almost nothing. Bucket each band by all r of its values, not one.")

    found = verify(cands, sh, THRESHOLD)
    assert found is not None, "verify returned None."
    found_rows = {(row["a"], row["b"]): row["j"] for row in found.collect()}
    assert set(found_rows) == truth & pairs, (
        "verify should keep exactly the candidates whose exact Jaccard similarity is at "
        f"least {THRESHOLD}: got {len(found_rows)}, expected {len(truth & pairs)}.")
    worst = max(abs(found_rows[p] - exact[p]) for p in found_rows)
    assert worst < 1e-9, "verify's `j` is not the exact Jaccard similarity."
    print(f"verify passes: {len(found_rows)} near-duplicate pairs, precision 1.0")

    # ---- Part 2: IVF ----
    X, Q = make_vectors(20000, 200)
    # Fixed slices (not local[*]'s core count) so k-means is the same everywhere
    sc = spark.sparkContext
    vectors = spark.createDataFrame(sc.parallelize([(i, X[i].tolist()) for i in range(len(X))], 4),
                                    "id int, v array<double>").cache()
    queries = spark.createDataFrame(sc.parallelize([(i, Q[i].tolist()) for i in range(len(Q))], 2),
                                    "qid int, q array<double>").cache()
    km = KMeans(k=64, seed=1, maxIter=20, featuresCol="f").fit(
        vectors.select(array_to_vector("v").alias("f")))
    centroids = [list(c) for c in km.clusterCenters()]
    C = np.array(centroids)

    index = assign_lists(vectors, centroids)
    assert index is not None, "assign_lists returned None."
    index = index.cache()
    got = dict(index.select("id", "list").collect())
    want = np.argmin(((X[:, None, :] - C[None, :, :]) ** 2).sum(-1), axis=1)
    wrong = sum(got[i] != want[i] for i in range(len(X)))
    assert wrong == 0, (
        f"{wrong} vectors were assigned to a centroid that is not their nearest. Lists are "
        "0-based: array_position is 1-based.")
    assert not [n for n in plan_nodes(index) if n in PYTHON_NODES], "assign_lists should not run Python."
    sizes = sorted((c for c in index.groupBy("list").count().toPandas()["count"]), reverse=True)
    print(f"IVF: 64 lists, sizes from {sizes[-1]} to {sizes[0]} (mean {np.mean(sizes):.0f})")

    exact_nn = np.argsort(((Q[:, None, :] - X[None, :, :]) ** 2).sum(-1), axis=1)[:, :10]
    brute = len(Q) * len(X)
    curve = []
    for nprobe in (1, 4, 8, 16, 64):
        scored = ivf_candidates(queries, index, centroids, nprobe)
        assert scored is not None, "ivf_candidates returned None."
        scored = scored.cache()
        work = scored.count()
        result = top_k(scored, 10)
        assert result is not None, "top_k returned None."
        res = {row["qid"]: row["ids"] for row in result.collect()}
        rec = float(np.mean([len(set(res.get(q, [])) & set(exact_nn[q])) / 10 for q in range(len(Q))]))
        curve.append((nprobe, rec, work))
        print(f"  nprobe={nprobe:2d}: recall@10={rec:.3f}, vectors scored {work} "
              f"({work / brute:.1%} of brute force)")
        scored.unpersist()
    (_, r1, w1), (_, r4, w4), (_, r8, w8), (_, r16, w16), (_, r64, w64) = curve
    assert w64 == brute and r64 == 1.0, (
        f"Probing all 64 lists must score every vector for every query ({brute}) and find "
        f"the exact neighbours; got {w64} scored, recall {r64:.3f}. Check top_k's ordering.")
    assert r1 <= r4 <= r8, "Recall should not drop when nprobe grows."
    assert w1 < w4 < w8, "More probes must score more vectors."
    assert r8 >= 0.88 and r16 >= 0.97, (
        f"recall@10 is {r8:.3f} at nprobe=8 and {r16:.3f} at nprobe=16; expected at least "
        "0.88 and 0.97. Probe the lists whose centroids are nearest to the query.")
    assert w8 <= 0.25 * brute, (
        f"nprobe=8 scored {w8} vectors, more than a quarter of brute force: is each query "
        "joined only to the lists it probes?")
    print(f"IVF passes: exact at full probe, recall {r8:.2f} at nprobe=8 for "
          f"{w8 / brute:.0%} of the work")

    spark.stop()
    print("All tests passed!")
