"""
Distributed Connected Components - Starter

The large-star / small-star algorithm (Kiveris et al., 2014) on DataFrames:
messy match edges cleaned into an undirected graph, each star operation
written so that it reads its input once, a local convergence test, and a
driver loop that checkpoints so the plan stays small. The harness checks the
result against a union-find on the same edges, bounds the number of rounds,
and measures the plan.
"""

import math
import random
import shutil
import tempfile

from pyspark.sql import SparkSession, Window, functions as F


# ---------------------------------------------------------------------------
# Part 1: edges and the two star operations
# ---------------------------------------------------------------------------

def clean_edges(raw):
    """Undirected, deduplicated edges as (src, dst) with src < dst. Drops
    rows with a NULL end and self-loops; (a, b) and (b, a) are one edge."""
    # TODO: filter out NULL ends and self-loops, select least(src, dst) as src
    # and greatest(src, dst) as dst, then distinct().
    return None


def large_star(edges):
    """For every node u and every neighbour v > u, emit (v, m(u)), where
    m(u) is the smallest of u and its neighbours. Reads `edges` once."""
    # TODO: one row per direction without a union: explode an array of two
    # structs (u, v). Then m = least(min(v) over Window.partitionBy("u"), u),
    # keep v > u, emit (v as src, m as dst), distinct().
    return None


def small_star(edges):
    """Orient every edge from its larger end u to its smaller end v. For
    every u, with m(u) the smallest of its smaller neighbours, emit (v, m(u))
    for each smaller neighbour v and (u, m(u)), dropping self-loops. Reads
    `edges` once."""
    # TODO: orient every edge as u = greatest, v = least. m = min(v) over
    # Window.partitionBy("u"). Emit (v, m) and (u, m) with one explode of an
    # array of two structs, drop rows where src == dst, distinct().
    return None


def is_converged(edges):
    """True when the edges are stars around the smallest node of each
    component: every src has exactly one dst, and no node is both a src and
    a dst."""
    # TODO: the largest number of rows per src must be 1 (or the table is
    # empty), and the set of dst values must not intersect the set of src values.
    return None


# ---------------------------------------------------------------------------
# Part 2: the driver loop
# ---------------------------------------------------------------------------

def connected_components(vertices, raw_edges, checkpoint_every=2, max_rounds=60, on_round=None):
    """Return (labels, rounds): labels has (id, component) for every row of
    vertices, component being the smallest id in its connected component;
    rounds is the number of large-star + small-star rounds run. Call
    on_round(edges) (when given) with the edges after each round."""
    # TODO: clean the edges, then loop: edges = small_star(large_star(edges)).
    # Every checkpoint_every rounds use localCheckpoint() (eager), otherwise
    # cache() and count(); unpersist the previous edges; call on_round(edges)
    # when it is given; stop when is_converged(edges) or after max_rounds.
    # Finally left-join vertices to the (src -> dst) labels; a vertex with no
    # label is its own component (coalesce).
    return None, 0


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

def union_find(nodes, edges):
    """Reference answer: node -> smallest node of its component."""
    parent = {n: n for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        if a is None or b is None:
            continue
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    return {n: find(n) for n in nodes}


def plan_leaves(df):
    return df._jdf.queryExecution().analyzed().collectLeaves().length()


def plan_lines(df):
    return df._jdf.queryExecution().analyzed().treeString().count("\n")


def optimized_lines(df):
    """Lines of the optimized plan. A cached DataFrame shows up as an
    InMemoryRelation that prints the plan it was cached from, so this grows
    with every round that was cached but never checkpointed."""
    return df._jdf.queryExecution().optimizedPlan().toString().count("\n")


def test_graphs(rng):
    """Disjoint graphs in one edge list, each in its own id range, with the
    mess an entity matcher produces: both directions, repeats, self-loops,
    NULLs. Returns (vertices, edges, names)."""
    edges, vertices, names = [], set(), {}

    def add(name, offset, es, extra=()):
        for a, b in es:
            edges.append((a + offset, b + offset))
            vertices.update((a + offset, b + offset))
        vertices.update(v + offset for v in extra)
        names[name] = offset

    n = 4096
    add("chain, ids in order", 0, [(i, i + 1) for i in range(n - 1)])
    perm = list(range(n))
    rng.shuffle(perm)
    add("chain, ids shuffled", 1_000_000, [(perm[i], perm[i + 1]) for i in range(n - 1)])
    add("star, hub has the largest id", 2_000_000, [(3000, i) for i in range(3000)])
    rnd = [(rng.randrange(3000), rng.randrange(3000)) for _ in range(2400)]
    add("random sparse graph", 3_000_000, [e for e in rnd if e[0] != e[1]], extra=range(3000))
    add("isolated vertices", 4_000_000, [], extra=range(50))
    messy = [(a, b) for a, b in edges[:500]]
    edges += [(b, a) for a, b in messy] + messy[:100]          # reversed and repeated
    edges += [(v, v) for v in list(vertices)[:40]]              # self-loops
    edges += [(None, 7), (8, None)]                             # broken matches
    return sorted(vertices), edges, names


if __name__ == "__main__":
    spark = (SparkSession.builder.master("local[*]")
             .config("spark.sql.shuffle.partitions", "4")
             .config("spark.ui.showConsoleProgress", "false")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    tmp = tempfile.mkdtemp()
    spark.sparkContext.setCheckpointDir(tmp)

    # ---- Part 1: clean_edges ----
    raw = spark.createDataFrame([(1, 2), (2, 1), (2, 1), (3, 3), (None, 4), (5, None), (6, 4)],
                                "src long, dst long")
    cleaned = clean_edges(raw)
    assert cleaned is not None, "clean_edges returned None."
    got = sorted(tuple(r) for r in cleaned.collect())
    assert got == [(1, 2), (4, 6)], (
        f"clean_edges gave {got}. Drop NULL ends and self-loops, put the smaller id in src, "
        "and deduplicate.")
    print("clean_edges passes")

    # ---- Part 1: one round on a small graph ----
    small = clean_edges(spark.createDataFrame([(1, 2), (2, 3), (3, 4), (4, 5), (7, 6)],
                                              "src long, dst long"))
    ls = large_star(small)
    assert ls is not None, "large_star returned None."
    got_ls = sorted(tuple(r) for r in ls.collect())
    assert got_ls == [(2, 1), (3, 1), (4, 2), (5, 3), (7, 6)], (
        f"large_star on the path 1-2-3-4-5 plus 6-7 gave {got_ls}; expected "
        "[(2, 1), (3, 1), (4, 2), (5, 3), (7, 6)]. For each u, link every larger neighbour v "
        "to m(u) = min(u, neighbours of u).")
    ss = small_star(ls)
    assert ss is not None, "small_star returned None."
    got_ss = sorted(tuple(r) for r in ss.collect())
    assert got_ss == [(2, 1), (3, 1), (4, 2), (5, 3), (7, 6)], (
        f"small_star after large_star gave {got_ss}. For each u, link u and every smaller "
        "neighbour to the smallest smaller neighbour; drop self-loops.")
    ss2 = small_star(clean_edges(spark.createDataFrame([(5, 1), (5, 3), (5, 2)], "src long, dst long")))
    got_ss2 = sorted(tuple(r) for r in ss2.collect())
    assert got_ss2 == [(2, 1), (3, 1), (5, 1)], (
        f"small_star on the star 5-1, 5-2, 5-3 gave {got_ss2}; expected [(2, 1), (3, 1), (5, 1)].")
    for name, f in (("large_star", large_star), ("small_star", small_star)):
        leaves = plan_leaves(f(small))
        assert leaves == 1, (
            f"{name} reads its input {leaves} times (the analyzed plan has {leaves} leaves). "
            "Every extra read multiplies the plan of the next round: use a window for the "
            "minimum and explode an array of structs instead of a union or a self-join.")
    print("large_star and small_star pass, and each reads its input once")

    # ---- Part 1: is_converged ----
    star = spark.createDataFrame([(2, 1), (3, 1), (9, 7)], "src long, dst long")
    assert is_converged(star) is True, "Stars around the smallest node are converged."
    assert is_converged(spark.createDataFrame([(3, 1), (3, 2)], "src long, dst long")) is False, (
        "Node 3 points to two nodes, so 1, 2 and 3 are not labelled yet.")
    assert is_converged(spark.createDataFrame([(2, 1), (3, 2)], "src long, dst long")) is False, (
        "Node 2 is both a leaf and a centre: 3 is not yet linked to 1.")
    print("is_converged passes")

    # ---- Part 2: the whole algorithm on messy test graphs ----
    rng = random.Random(49)
    nodes, edges, names = test_graphs(rng)
    vdf = spark.createDataFrame([(v,) for v in nodes], "id long")
    edf = spark.createDataFrame(edges, "src long, dst long")
    seen = []

    def watch(e):
        seen.append((plan_lines(e), optimized_lines(e)))
        assert seen[-1][1] <= 200, (
            f"After round {len(seen)} the optimized plan has {seen[-1][1]} lines: the lineage "
            "of earlier rounds is still in it (a cached DataFrame prints the plan it came from, "
            "and that doubles every round). Checkpoint (localCheckpoint() or checkpoint()) every "
            "checkpoint_every rounds, or the driver runs out of memory printing plans.")

    result = connected_components(vdf, edf, checkpoint_every=2, on_round=watch)
    assert result is not None and result[0] is not None, "connected_components returned None."
    labels, rounds = result
    got = {r["id"]: r["component"] for r in labels.collect()}
    want = union_find(nodes, edges)
    assert set(got) == set(want), (
        f"labels has {len(got)} ids, expected one per vertex ({len(want)}). Isolated vertices "
        "and the smallest node of each component must be there too (left join from vertices).")
    for name, offset in names.items():
        bad = [v for v in want if offset <= v < offset + 1_000_000 and got[v] != want[v]]
        assert not bad, (
            f"{name}: {len(bad)} vertices have the wrong component, for example {bad[0]} got "
            f"{got[bad[0]]}, expected {want[bad[0]]}.")
    comps = len(set(want.values()))
    bound = 2 * math.ceil(math.log2(4096))
    print(f"{len(nodes)} vertices, {len(edges)} raw edges, {comps} components, {rounds} rounds")
    assert rounds <= bound, (
        f"{rounds} rounds for a 4096-node chain; large-star / small-star should need at most "
        f"{bound} (2 log2 n). Naive label propagation would need 4095.")
    assert len(seen) == rounds, (
        f"on_round was called {len(seen)} times for {rounds} rounds. Call it once per round "
        "with the new edges.")
    print("plan lines per round (analyzed, optimized):", seen)
    assert max(a for a, _ in seen) <= 60, "The analyzed plan keeps growing: checkpoint the edges."
    print("connected_components matches union-find on every test graph")

    # ---- Part 2: reposted listings ----
    listings = spark.read.json("data/messy/listings/listings.jsonl").select("listing_id", "description")
    docs = {r["listing_id"]: r["description"].lower() for r in listings.collect()}
    sh = {k: {t[i:i + 5] for i in range(len(t) - 4)} for k, t in docs.items()}
    ids = sorted(sh)
    pairs = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]
             if len(sh[a] & sh[b]) / len(sh[a] | sh[b]) >= 0.5]
    ldf = spark.createDataFrame([(k,) for k in ids], "id string")
    pdf = spark.createDataFrame(pairs, "src string, dst string")
    clusters, r2 = connected_components(ldf, pdf)
    got = {r["id"]: r["component"] for r in clusters.collect()}
    assert got == union_find(ids, pairs), "The listing clusters differ from union-find."
    sizes = sorted((n for n in clusters.groupBy("component").count().toPandas()["count"]), reverse=True)
    print(f"listings: {len(pairs)} pairs with J >= 0.5, {len(sizes)} clusters in {r2} rounds, "
          f"largest {sizes[:5]}")

    spark.stop()
    shutil.rmtree(tmp, ignore_errors=True)
    print("All tests passed!")
