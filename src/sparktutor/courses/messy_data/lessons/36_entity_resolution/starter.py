"""
Deduplication and Entity Resolution - Exercise

The same customers live in a CRM, a web shop and a support desk, each with
its own typos, formats and gaps. Unify the three, normalize the matching
keys, block to avoid comparing every pair, score candidate pairs, cluster
the matches into entities with label propagation, and build one golden
record per entity. data/messy/entities/truth.csv is the answer key.
"""

import tempfile
import unicodedata

import pandas as pd
from pyspark.sql import SparkSession, Window, functions as F

ENTITIES = "data/messy/entities"
SUPPORT_SCHEMA = "contact_id string, name string, email string, phone string, seen timestamp"
RECORD_COLUMNS = ["source", "record_id", "name", "email", "phone", "city", "updated_at"]
MATCH_THRESHOLD = 0.9

# Nicknames mapped to the formal name, lower case and without accents.
NICKNAMES = {
    "bob": "robert", "rob": "robert", "bill": "william", "will": "william",
    "liz": "elizabeth", "beth": "elizabeth", "kate": "katherine", "kathy": "katherine",
    "mike": "michael", "jen": "jennifer", "tom": "thomas", "maggie": "margaret",
    "peggy": "margaret", "dan": "daniel", "chris": "christopher", "alex": "alexander",
    "nick": "nicholas", "jon": "jonathan", "sam": "samantha", "ben": "benjamin",
}


# ---- Plain Python helpers (given) ----

def strip_accents(s):
    """Remove accents: 'Nguyễn Côté' -> 'Nguyen Cote'. Đ/đ are separate letters in Unicode
    (not D plus a mark), so they are mapped by hand. None stays None."""
    if s is None:
        return None
    s = s.replace("Đ", "D").replace("đ", "d")
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def jaro_winkler(s1, s2, prefix_weight=0.1):
    """Jaro-Winkler similarity between two strings: 1.0 identical, 0.0 nothing in common.

    Jaro counts characters that match within a window and how many of them
    are out of order; Winkler adds a bonus for a common prefix (up to 4
    characters), because typos are rarer at the start of a name.
    """
    if s1 is None or s2 is None:
        return None
    if s1 == s2:
        return 1.0
    l1, l2 = len(s1), len(s2)
    if l1 == 0 or l2 == 0:
        return 0.0
    window = max(max(l1, l2) // 2 - 1, 0)
    used1, used2 = [False] * l1, [False] * l2
    matches = 0
    for i, ch in enumerate(s1):
        for j in range(max(0, i - window), min(l2, i + window + 1)):
            if not used2[j] and s2[j] == ch:
                used1[i] = used2[j] = True
                matches += 1
                break
    if matches == 0:
        return 0.0
    k = transposed = 0
    for i in range(l1):
        if used1[i]:
            while not used2[k]:
                k += 1
            if s1[i] != s2[k]:
                transposed += 1
            k += 1
    jaro = (matches / l1 + matches / l2 + (matches - transposed / 2) / matches) / 3
    prefix = 0
    for a, b in zip(s1[:4], s2[:4]):
        if a != b:
            break
        prefix += 1
    return jaro + prefix * prefix_weight * (1 - jaro)


def name_similarity(tokens1, tokens2):
    """Similarity of two names given as lists of tokens, in any order.

    Each token is matched to its most similar token in the other name
    (Jaro-Winkler); the average is taken in both directions and the lower
    one is kept, so an extra token ("Văn" in one system only) costs
    something but a reordered name costs nothing. None if either is empty.
    """
    if tokens1 is None or tokens2 is None or len(tokens1) == 0 or len(tokens2) == 0:
        return None

    def one_way(a, b):
        return sum(max(jaro_winkler(x, y) for y in b) for x in a) / len(a)

    return min(one_way(list(tokens1), list(tokens2)), one_way(list(tokens2), list(tokens1)))


# ---- Your code ----

def load_records(spark):
    """The three systems as one DataFrame with RECORD_COLUMNS.

    - crm.csv (header): record_id = crm_id, name = first_name and last_name joined by a
      space, updated_at = to_date(updated_at)
    - shop.csv (header): record_id = customer_no; a name with a comma is "Last, First"
      and becomes "First Last"; updated_at = to_date(last_order)
    - support.jsonl (SUPPORT_SCHEMA): record_id = contact_id, city is NULL,
      updated_at = to_date(seen)
    source is "crm", "shop" or "support".
    """
    # TODO: read crm.csv with option("header", True); name = F.concat_ws(" ", "first_name", "last_name")
    # TODO: read shop.csv; for names with a comma, F.split("name", ",") gives [last, first]: rebuild "first last"
    # TODO: read support.jsonl with spark.read.schema(SUPPORT_SCHEMA).json(...); city is F.lit(None).cast("string")
    # TODO: give all three RECORD_COLUMNS (updated_at with F.to_date) and combine with unionByName
    return None


def normalize(records):
    """Add the matching keys:

    - id: source and record_id joined with ":" (unique across systems)
    - tokens: the name lower-cased, accents removed (strip_accents in a UDF), anything
      but a-z and spaces removed, split on spaces, empty tokens dropped, nicknames
      replaced by NICKNAMES, sorted (array<string>)
    - name_key: tokens joined with one space
    - email_key: trimmed and lower-cased; for gmail.com also drop dots and anything
      after "+" in the local part; NULL when empty
    - phone_key: the last 10 digits of phone; NULL when there are none
    - city_key: city lower-cased without accents
    """
    # TODO: wrap strip_accents in a pandas UDF (s.map(strip_accents)) returning string
    # TODO: tokens: lower, unaccent, regexp_replace "[^a-z ]" with "", split on " +", F.filter out "",
    # TODO:       F.transform each token with F.coalesce(F.element_at(nickname_map, t), t), then F.array_sort
    # TODO:       (build nickname_map with F.create_map from NICKNAMES)
    # TODO: email_key: F.nullif(F.lower(F.trim("email")), F.lit("")); for gmail.com remove dots and the +tag
    # TODO: phone_key: F.right of the digits only, 10 characters, NULL when empty; city_key: lower and unaccent
    # TODO: return records with id, tokens, name_key, email_key, phone_key, city_key added
    return None


def candidate_pairs(norm):
    """Candidate pairs (l, r) with l < r (ids), from three blocking passes, without duplicates:

    1. the same email_key
    2. the same phone_key
    3. at least one name token (2 letters or more) with the same soundex code
    NULL keys never block together.
    """
    # TODO: write a helper that self-joins a DataFrame (id, bk) on bk, drops NULL bk and keeps a.id < b.id
    # TODO: pass 1: email_key, pass 2: phone_key, pass 3: F.soundex of each exploded token with length > 1
    # TODO: union the three (unionByName) and drop duplicate pairs with distinct()
    return None


def score_pairs(norm, candidates):
    """Score each candidate pair: columns l, r, name_sim, score.

    name_sim = name_similarity(l tokens, r tokens) in a pandas UDF. Then add evidence
    from the other keys: +0.5 for the same email_key, -0.3 for two different ones;
    +0.3 for the same phone_key, -0.2 for two different ones; +0.1 for the same
    city_key, -0.05 for two different ones; 0 when either side is NULL.
    score = name_sim + the three evidence values.
    """
    # TODO: wrap name_similarity in a pandas UDF returning double
    # TODO: join candidates to two prefixed copies of norm (l_..., r_...) on l == l_id and r == r_id
    # TODO: evidence(key, agree, disagree): 0.0 if either side is NULL, +agree if equal, -disagree otherwise
    # TODO: score = name_sim + email (0.5, 0.3) + phone (0.3, 0.2) + city (0.1, 0.05); select l, r, name_sim, score
    return None


def precision_recall(scored, true_pairs, threshold):
    """(precision, recall) of calling a pair a match when score >= threshold.

    true_pairs has columns l, r (l < r) for every pair of records of the same
    entity, including pairs blocking never proposed (they count against recall).
    Precision is 0.0 when nothing is predicted.
    """
    # TODO: predicted = pairs with score >= threshold; tp = predicted joined to true_pairs on l, r
    # TODO: return (tp / predicted, tp / true pairs), with precision 0.0 when nothing is predicted
    return None


def connected_components(ids, edges, max_iterations=20):
    """Label every id with the smallest id reachable through edges (l, r).

    Iterative label propagation: start with label = id; in each round every id
    takes the smallest label among itself and its neighbours (edges in both
    directions). Stop when a round changes nothing. Cut the lineage each round
    with localCheckpoint(). Return (labels with columns id, label; the number of
    rounds run, counting the final round that changed nothing).
    """
    # TODO: make edges symmetric (l->r and r->l), start labels with label = id
    # TODO: each round: for every id, the min label offered by its neighbours, then least(label, offer)
    # TODO: localCheckpoint() the new labels, count how many changed, stop when 0
    # TODO: return (labels, rounds)
    return None


def golden_records(norm, labels):
    """One row per entity (label), built with survivorship rules:

    - name: first find the entity's most frequent name_key (mode, deterministic=True),
      so a one-off typo loses the vote. Among the records with that name_key, take the
      cleaned name (spaces collapsed, trimmed, initcap) preferring, in order: a name
      written in full (its own tokens, lower-cased without accents and sorted, equal
      the name_key, so no nickname), a name with accents, the most recent record.
    - email: email_key of the most recent record that has one
    - phone: the most frequent phone_key (mode, deterministic=True)
    - city: the city of the most recent record that has one (as written)
    - sources: sorted distinct sources, records: number of records,
      last_seen: the latest updated_at
    Columns: label, name, email, phone, city, sources, records, last_seen.
    """
    # TODO: join norm to labels on id; add clean (collapsed spaces, trim, initcap) and plain (unaccented clean)
    # TODO: name: per label, F.mode("name_key", deterministic=True); keep rows with that name_key; then
    # TODO:       F.max_by("clean", F.struct(written_in_full, has_accent, F.col("updated_at")))
    # TODO: email/city: F.max_by(col, F.when(col.isNotNull(), F.col("updated_at"))) so NULLs never win
    # TODO: phone: F.mode("phone_key", deterministic=True); sources: F.array_sort(F.collect_set("source"))
    # TODO: records: F.count("*"); last_seen: F.max("updated_at"); join names and the rest on label
    return None


# ---- Test harness ----
if __name__ == "__main__":
    import csv
    from collections import defaultdict

    spark = (SparkSession.builder
             .appName("EntityResolution")
             .master("local[*]")
             .config("spark.sql.shuffle.partitions", "4")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    with open(f"{ENTITIES}/truth.csv") as f:
        truth = {f"{r['source']}:{r['record_id']}": r["entity_id"] for r in csv.DictReader(f)}
    members = defaultdict(list)
    for rid, ent in truth.items():
        members[ent].append(rid)
    true_pair_set = {tuple(sorted((a, b))) for ids in members.values() for a in ids for b in ids if a < b}
    true_pairs = spark.createDataFrame(sorted(true_pair_set), "l string, r string")

    def union_find(ids, edges):
        parent = {i: i for i in ids}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for a, b in edges:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
        return {i: find(i) for i in ids}

    try:
        # 1. Load
        records = load_records(spark)
        assert records is not None, "load_records returned None"
        assert records.columns == RECORD_COLUMNS, f"Expected columns {RECORD_COLUMNS}; got {records.columns}"
        by_source = {r.source: r["count"] for r in records.groupBy("source").count().collect()}
        assert by_source == {"crm": 55, "shop": 44, "support": 40}, (
            f"Expected 55 crm, 44 shop and 40 support records, got {by_source}")
        rec = {f"{r.source}:{r.record_id}": r for r in records.collect()}
        assert rec["shop:10018"].name == "José Smith", (
            f"shop 10018 is 'Smith, José' and should become 'José Smith', got {rec['shop:10018'].name!r}")
        assert str(rec["support:S-001"].updated_at) == "2024-12-09", (
            f"updated_at for support should be to_date(seen), got {rec['support:S-001'].updated_at}")

        # 2. Normalize
        norm = normalize(records)
        assert norm is not None, "normalize returned None"
        for c in ["id", "tokens", "name_key", "email_key", "phone_key", "city_key"]:
            assert c in norm.columns, f"normalize should add {c}; got {norm.columns}"
        norm = norm.localCheckpoint()
        n = {r.id: r for r in norm.collect()}
        assert len(n) == 139, f"ids should be unique: expected 139, got {len(n)}"
        assert n["crm:CRM-0005"].name_key == "singh william", (
            f"'Bill Singh' should normalize to 'singh william' (nickname, sorted), got {n['crm:CRM-0005'].name_key!r}")
        assert n["crm:CRM-0004"].email_key == "mateogarcia@gmail.com", (
            f"Gmail ignores dots and +tags: expected mateogarcia@gmail.com, got {n['crm:CRM-0004'].email_key!r}")
        assert n["crm:CRM-0006"].email_key == "robert.ahmed@example.ca", (
            "Trim and lower-case e-mails; only gmail.com addresses lose their dots")
        assert n["crm:CRM-0002"].phone_key == "4165550943", (
            f"phone_key should be the last 10 digits, got {n['crm:CRM-0002'].phone_key!r}")
        assert n["crm:CRM-0008"].email_key is None, "An empty e-mail should give a NULL email_key"
        assert n["crm:CRM-0003"].city_key == "quebec", f"city_key should drop accents and case, got {n['crm:CRM-0003'].city_key!r}"

        # 3. Blocking
        cands = candidate_pairs(norm)
        assert cands is not None, "candidate_pairs returned None"
        assert cands.columns == ["l", "r"], f"Expected columns l, r; got {cands.columns}"
        cands = cands.localCheckpoint()
        cand_set = {(r.l, r.r) for r in cands.collect()}
        assert all(l < r for l, r in cand_set), "Keep each pair once, with l < r"
        all_pairs = 139 * 138 // 2
        found = len(cand_set & true_pair_set)
        assert found == len(true_pair_set), (
            f"Blocking should keep all {len(true_pair_set)} true pairs, kept {found}; "
            "use all three passes (email, phone, soundex of every name token)")
        assert len(cand_set) < 0.15 * all_pairs, (
            f"{len(cand_set)} candidates is too many (all pairs: {all_pairs}); block, don't cross join")
        print(f"Blocking: {len(cand_set)} of {all_pairs} pairs ({len(cand_set) / all_pairs:.1%}), "
              f"all {found} true pairs kept")

        # 4. Scoring
        scored = score_pairs(norm, cands)
        assert scored is not None, "score_pairs returned None"
        assert scored.columns == ["l", "r", "name_sim", "score"], (
            f"Expected columns l, r, name_sim, score; got {scored.columns}")
        scored = scored.localCheckpoint()
        s = {(r.l, r.r): r for r in scored.collect()}
        assert len(s) == len(cand_set), "score_pairs should keep every candidate pair"
        for (l, r), row in s.items():
            want = name_similarity(n[l].tokens, n[r].tokens)
            assert row.name_sim is not None and abs(row.name_sim - want) < 1e-9, (
                f"{l} / {r}: name_sim should be {want}, got {row.name_sim}")
        fam = s[("support:S-006", "support:S-040")]
        assert fam.score < MATCH_THRESHOLD, (
            f"S-006 and S-040 are two people of one family sharing a phone; their score {fam.score:.3f} "
            "should stay below the threshold (different names, and a different e-mail would count against)")

        # 5. Precision and recall per threshold
        curve = {}
        for th in [0.8, MATCH_THRESHOLD, 1.1]:
            pr = precision_recall(scored, true_pairs, th)
            assert pr is not None, "precision_recall returned None"
            curve[th] = pr
            print(f"threshold {th}: precision {pr[0]:.3f}, recall {pr[1]:.3f}")
        assert curve[0.8][0] < curve[MATCH_THRESHOLD][0] <= curve[1.1][0], "Precision should rise with the threshold"
        assert curve[0.8][1] >= curve[MATCH_THRESHOLD][1] >= curve[1.1][1], "Recall should fall with the threshold"
        assert curve[MATCH_THRESHOLD][0] >= 0.98 and curve[MATCH_THRESHOLD][1] >= 0.98, (
            f"At threshold {MATCH_THRESHOLD} expect precision and recall of at least 0.98, got {curve[MATCH_THRESHOLD]}")

        # 6. Clustering
        edges = scored.filter(F.col("score") >= MATCH_THRESHOLD).select("l", "r")
        result = connected_components(norm.select("id"), edges)
        assert result is not None and result[0] is not None, "connected_components returned None"
        labels, rounds = result
        got = {r.id: r.label for r in labels.collect()}
        want = union_find(list(n), [(r.l, r.r) for r in edges.collect()])
        assert got == want, (
            f"{sum(got.get(k) != v for k, v in want.items())} labels differ from union-find; every id "
            "should end with the smallest id in its component")
        assert rounds <= 10, f"Label propagation took {rounds} rounds; it should converge in a few"
        plan = labels._jdf.queryExecution().optimizedPlan().toString()
        assert len(plan) < 2000, (
            f"The final labels' plan is {len(plan)} characters long; call localCheckpoint() every round")
        clusters = defaultdict(set)
        for rid, lab in got.items():
            clusters[lab].add(rid)
        pred_pairs = {tuple(sorted((a, b))) for ids in clusters.values() for a in ids for b in ids if a < b}
        tp = len(pred_pairs & true_pair_set)
        print(f"Clusters: {len(clusters)} entities (truth: {len(members)}), {rounds} rounds; "
              f"pairwise precision {tp / len(pred_pairs):.3f}, recall {tp / len(true_pair_set):.3f}")
        merged = [sorted({truth[i] for i in ids}) for ids in clusters.values() if len({truth[i] for i in ids}) > 1]
        print("Clusters that merged different people:", merged)

        # 7. Golden records
        gold = golden_records(norm, labels)
        assert gold is not None, "golden_records returned None"
        assert gold.columns == ["label", "name", "email", "phone", "city", "sources", "records", "last_seen"], (
            f"Unexpected columns {gold.columns}")
        g = {r.label: r for r in gold.collect()}
        assert len(g) == len(clusters), f"Expected one golden record per cluster ({len(clusters)}), got {len(g)}"
        for lab, row in g.items():
            ids = clusters[lab]
            assert row.records == len(ids), f"{lab}: records should be {len(ids)}, got {row.records}"
            dated = sorted((n[i].updated_at, i) for i in ids if n[i].city is not None)
            if dated:
                assert row.city == n[dated[-1][1]].city, (
                    f"{lab}: city should come from the most recent record with a city ({n[dated[-1][1]].city}), "
                    f"got {row.city}; use max_by with NULL ordering for rows without a city")
            dated = sorted((n[i].updated_at, i) for i in ids if n[i].email_key is not None)
            if dated:
                assert row.email == n[dated[-1][1]].email_key, f"{lab}: email should be the most recent email_key"
            assert row.sources == sorted({n[i].source for i in ids}), f"{lab}: sources should be sorted distinct"
        trang = [r for r in g.values() if "Trang" in r.name]
        assert trang and "Phạm" in trang[0].name, (
            f"The golden name should keep accents when any record has them, got {[r.name for r in trang]}")
        gold.orderBy(F.desc("records"), "label").show(8, truncate=False)
        print("All tests passed!")
    finally:
        spark.stop()
