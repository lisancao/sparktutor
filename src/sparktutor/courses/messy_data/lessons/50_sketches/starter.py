"""
Sketches: HLL, Theta and KLL from the Inside - Starter

Daily sketches of a week of messy events (distinct users with HLL and theta,
latency quantiles with KLL) stored as BINARY columns in Parquet, then rolled
up without the raw data: weekly and per-country distinct users, users seen on
two given days (a theta intersection) and weekly latency quantiles. The
harness deletes the raw events before the rollups run and checks every answer
against the exact value and the error bound DataSketches documents.
"""

import bisect
import json
import os
import random
import shutil
import tempfile

from pyspark.sql import SparkSession, functions as F

HLL_LG_K = 14
THETA_LG_K = 12
KLL_K = 200


# ---------------------------------------------------------------------------
# Part 1: daily sketches
# ---------------------------------------------------------------------------

def normalize_user(col):
    """The user id as one value per person: trimmed, lower case, and NULL
    when nothing is left (sketches would skip "" anyway; exact counts would
    not)."""
    # TODO: F.lower(F.trim(col)), and NULL when the result is "".
    return None


def daily_sketches(events):
    """One row per (day, country) with:
    users_hll (hll_sketch_agg, lgConfigK HLL_LG_K), users_theta
    (theta_sketch_agg, lgNomEntries THETA_LG_K), latency_kll
    (kll_sketch_agg_double, k KLL_K) and events (an exact count)."""
    # TODO: group by day and country; aggregate hll_sketch_agg(user, HLL_LG_K),
    # theta_sketch_agg(user, THETA_LG_K), kll_sketch_agg_double("latency_ms",
    # KLL_K) and count("*"), with user = normalize_user(F.col("user")).
    return None


# ---------------------------------------------------------------------------
# Part 2: rollups that read only the sketches
# ---------------------------------------------------------------------------

def weekly_distinct(sketches):
    """(country, users): estimated distinct users per country over all days,
    plus a row with country NULL for all countries together."""
    # TODO: per country, hll_sketch_estimate(hll_union_agg("users_hll"));
    # then the same over every row with country as a NULL string; unionByName.
    return None


def returning_users(sketches, day_a, day_b):
    """One row: `sketch`, the theta sketch of users seen on both days (all
    countries), and `estimate`, its estimate."""
    # TODO: for each day, theta_union_agg the countries' users_theta; cross
    # join the two one-row results, theta_intersection them as `sketch`,
    # and add theta_sketch_estimate(sketch) as `estimate`.
    return None


def latency_quantiles(sketches, ranks):
    """A list of estimated latency quantiles over all days and countries,
    one per rank in `ranks`."""
    # TODO: kll_merge_agg_double("latency_kll"), then
    # kll_sketch_get_quantile_double(merged, F.lit(rank)) for every rank.
    return None


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

COUNTRIES = ["CA", "US", "VN", "FR", "BR"]


def write_raw_events(root, rng, days=7):
    """A week of events as JSON Lines, one folder per day. Users return from
    day to day; some ids arrive in upper case, with spaces, empty or NULL.
    Returns the exact answers computed in plain Python."""
    pool = [f"u{n:05d}" for n in range(40000)]
    home = {u: rng.choice(COUNTRIES) for u in pool}
    truth = {"users": {}, "latency": []}
    active_prev = set()
    for day in range(days):
        returning = [u for u in active_prev if rng.random() < 0.45]
        fresh = rng.sample(pool, 9000)
        active = set(returning) | set(fresh)
        folder = os.path.join(root, f"day={day}")
        os.makedirs(folder)
        with open(os.path.join(folder, "events.jsonl"), "w") as f:
            for u in sorted(active):
                truth["users"].setdefault(day, set()).add(u)
                for _ in range(rng.randint(1, 5)):
                    raw = u
                    roll = rng.random()
                    if roll < 0.08:
                        raw = u.upper()
                    elif roll < 0.12:
                        raw = f"  {u} "
                    ms = round(rng.lognormvariate(4.0, 0.8), 2)
                    truth["latency"].append(ms)
                    f.write(json.dumps({"user": raw, "country": home[u], "latency_ms": ms}) + "\n")
            for _ in range(300):        # broken tracker rows
                ms = round(rng.lognormvariate(4.0, 0.8), 2)
                truth["latency"].append(ms)
                f.write(json.dumps({"user": rng.choice(["", None]), "country": rng.choice(COUNTRIES),
                                    "latency_ms": ms}) + "\n")
        active_prev = active
    truth["home"] = home
    return truth


if __name__ == "__main__":
    spark = (SparkSession.builder.master("local[*]")
             .config("spark.sql.shuffle.partitions", "8")
             .config("spark.ui.showConsoleProgress", "false")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    jvm = spark._jvm
    tmp = tempfile.mkdtemp()
    raw_dir, sketch_dir = os.path.join(tmp, "raw"), os.path.join(tmp, "sketches")
    truth = write_raw_events(raw_dir, random.Random(50))

    # ---- Part 1: normalize_user ----
    probe = spark.createDataFrame([("u00001",), (" U00001 ",), ("U00001",), ("",), ("  ",), (None,)], "user string")
    expr = normalize_user(F.col("user"))
    assert expr is not None, "normalize_user returned None. Return a Column expression."
    norm = [r[0] for r in probe.select(expr).collect()]
    assert norm == ["u00001", "u00001", "u00001", None, None, None], (
        f"normalize_user gave {norm}; expected the same id three times, then NULL for empty, "
        "blank and NULL ids.")

    # ---- Part 1: daily sketches ----
    events = spark.read.json(raw_dir)            # day comes from the day=N folder names
    daily = daily_sketches(events)
    assert daily is not None, "daily_sketches returned None."
    daily.write.mode("overwrite").partitionBy("day").parquet(sketch_dir)
    stored = spark.read.parquet(sketch_dir)
    types = dict(stored.dtypes)
    for c in ("users_hll", "users_theta", "latency_kll"):
        assert types.get(c) == "binary", f"Column {c} should be stored as BINARY, found {types.get(c)}."
    n_rows = stored.count()
    assert n_rows == 7 * len(COUNTRIES), (
        f"The sketch table has {n_rows} rows; expected one per day and country "
        f"({7 * len(COUNTRIES)}).")
    raw_bytes = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(raw_dir) for f in fs)
    sk_bytes = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(sketch_dir) for f in fs)
    print(f"raw events: {raw_bytes / 1e6:.1f} MB; daily sketches: {sk_bytes / 1e6:.2f} MB "
          f"({n_rows} rows)")
    lg = jvm.org.apache.datasketches.hll.HllSketch.heapify(bytearray(stored.first()["users_hll"])).getLgConfigK()
    assert lg == HLL_LG_K, f"users_hll was built with lgConfigK {lg}; use {HLL_LG_K}."

    # The rollups below may only read the sketches: the raw data is gone.
    shutil.rmtree(raw_dir)
    sketches = spark.read.parquet(sketch_dir)

    def only_sketch_files(df, name):
        files = df.inputFiles()
        assert files and all(sketch_dir in f for f in files), (
            f"{name} reads {files[:2]}; a rollup must read only the sketch table.")

    # ---- Part 2: weekly distinct users ----
    week = weekly_distinct(sketches)
    assert week is not None, "weekly_distinct returned None."
    only_sketch_files(week, "weekly_distinct")
    got = {r["country"]: r["users"] for r in week.collect()}
    all_users = set().union(*truth["users"].values())
    exact = {None: len(all_users)}
    for c in COUNTRIES:
        exact[c] = sum(1 for u in all_users if truth["home"][u] == c)
    # 3 standard deviations, for a sketch built by merging (out of order)
    bound = jvm.org.apache.datasketches.hll.HllSketch.getRelErr(True, True, HLL_LG_K, 3)
    daily_sum = sum(len(s) for s in truth["users"].values())
    print(f"distinct users over the week: exact {exact[None]}, estimate {got.get(None):.0f}; "
          f"adding the daily counts would say {daily_sum}")
    assert set(got) == set(exact), f"weekly_distinct should return the countries and a NULL row, got {sorted(got, key=str)}."
    for c, e in exact.items():
        err = abs(got[c] - e) / e
        assert err <= bound, (
            f"Weekly distinct users for {c or 'all countries'}: estimate {got[c]:.0f}, exact {e}, "
            f"error {err:.2%} is above the 3-sigma bound {bound:.2%}. Union the HLL sketches "
            "(hll_union_agg) and normalize the ids before sketching.")
    print(f"weekly_distinct passes: every country within {bound:.2%} (3 sigma)")

    # ---- Part 2: users seen on day 5 and day 6 ----
    ret = returning_users(sketches, 5, 6)
    assert ret is not None, "returning_users returned None."
    only_sketch_files(ret, "returning_users")
    row = ret.first()
    both = len(truth["users"][5] & truth["users"][6])
    Mem = jvm.org.apache.datasketches.memory.Memory
    sk = jvm.org.apache.datasketches.theta.Sketch.heapify(Mem.wrap(bytearray(row["sketch"])))
    lo, hi = sk.getLowerBound(3), sk.getUpperBound(3)
    print(f"users on both day 5 and day 6: exact {both}, estimate {row['estimate']:.0f}, "
          f"3-sigma interval [{lo:.0f}, {hi:.0f}]")
    assert abs(row["estimate"] - sk.getEstimate()) <= 0.5, (
        "estimate must be theta_sketch_estimate of `sketch` (a BIGINT, the rounded estimate).")
    assert lo <= both <= hi, (
        f"The exact answer {both} is outside the sketch's 3-sigma interval [{lo:.0f}, {hi:.0f}]. "
        "Union each day's theta sketches first, then intersect the two days.")

    # ---- Part 2: latency quantiles ----
    ranks = [0.5, 0.9, 0.99]
    qs = latency_quantiles(sketches, ranks)
    assert qs is not None and len(qs) == len(ranks), "latency_quantiles should return one value per rank."
    lat = sorted(truth["latency"])
    # The bound DataSketches documents for this k, read from a merged sketch
    merged = sketches.agg(F.kll_merge_agg_double("latency_kll").alias("k")).first()["k"]
    kll = jvm.org.apache.datasketches.kll.KllDoublesSketch.heapify(Mem.wrap(bytearray(merged)))
    eps = kll.getNormalizedRankError(False)
    assert kll.getK() == KLL_K, f"latency_kll was built with k={kll.getK()}; use k={KLL_K}."
    for r, q in zip(ranks, qs):
        true_rank = bisect.bisect_right(lat, q) / len(lat)
        print(f"  p{int(r * 100)}: estimate {q:.2f} ms, exact {lat[int(r * len(lat))]:.2f} ms, "
              f"rank of the estimate {true_rank:.4f}")
        assert abs(true_rank - r) <= eps, (
            f"The p{int(r * 100)} estimate {q:.2f} has true rank {true_rank:.4f}, further than "
            f"the normalized rank error {eps:.4f} from {r}. Merge the daily KLL sketches with "
            "kll_merge_agg_double, then kll_sketch_get_quantile_double.")
    print(f"latency_quantiles passes: rank error within {eps:.2%}")

    spark.stop()
    shutil.rmtree(tmp, ignore_errors=True)
    print("All tests passed!")
