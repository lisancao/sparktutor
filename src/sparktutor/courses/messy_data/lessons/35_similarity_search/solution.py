"""
Feature Vectors and Similarity Search - Solution

Turn every image and audio clip in data/messy/media_library into a feature
vector, find each file's most similar file exactly (a self join and the 4.2
vector_cosine_similarity function), then approximately with MLlib's
BucketedRandomProjectionLSH, and measure how much the approximation misses.
"""

import io
import wave

import numpy as np
import pandas as pd
from pyspark.ml.feature import BucketedRandomProjectionLSH
from pyspark.ml.functions import array_to_vector
from pyspark.sql import SparkSession, Window, functions as F

LIBRARY = "data/messy/media_library"
IMAGES = f"{LIBRARY}/images"
AUDIO = f"{LIBRARY}/audio"
LABELS = f"{LIBRARY}/labels.csv"
COLOR_BINS = 4          # 4 levels per channel: 4 * 4 * 4 = 64 colour bins
AUDIO_BANDS = 16        # 16 bands of 125 Hz between 0 and 2000 Hz
TOP_HZ = 2000.0


# ---- Feature functions: plain Python and NumPy, no Spark (given) ----

def color_histogram(data, channels, bins=COLOR_BINS):
    """Joint colour histogram of decoded pixels from the image source.

    data holds height * width * channels bytes in B, G, R(, A) order; gray
    images have one channel. Returns bins**3 float32 values that sum to 1:
    the fraction of pixels in each (red, green, blue) cell.
    """
    px = np.frombuffer(data, dtype=np.uint8).reshape(-1, channels)
    if channels == 1:
        b = g = r = px[:, 0]
    else:
        b, g, r = px[:, 0], px[:, 1], px[:, 2]          # alpha (if any) is ignored
    step = 256 // bins
    cell = (r // step).astype(int) * bins * bins + (g // step).astype(int) * bins + (b // step).astype(int)
    return (np.bincount(cell, minlength=bins ** 3) / len(cell)).astype(np.float32)


def band_energies(content, bands=AUDIO_BANDS, top_hz=TOP_HZ):
    """Share of a WAV clip's energy in each frequency band between 0 and top_hz.

    The bands are in hertz, computed from the clip's own sample rate, so a
    clip saved at 8000 samples per second lands in the same bands as the
    same sound at 4000. Returns None for a silent clip.
    """
    with wave.open(io.BytesIO(content)) as w:
        rate = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    power = np.abs(np.fft.rfft(x)) ** 2
    freqs = np.fft.rfftfreq(len(x), d=1.0 / rate)
    band = (freqs / (top_hz / bands)).astype(int)
    keep = band < bands
    energy = np.bincount(band[keep], weights=power[keep], minlength=bands)
    total = energy.sum()
    return (energy / total).astype(np.float32) if total > 0 else None


# ---- Your code ----

def image_vectors(spark, folder=IMAGES):
    """One row per valid image: file (the file name) and features (array<float>, 64 values).

    Read with format("image"); skip files the image source could not decode
    (nChannels is -1 for them). Compute features with a pandas UDF that calls
    color_histogram(data, channels).
    """
    @F.pandas_udf("array<float>")
    def histogram(data: pd.Series, channels: pd.Series) -> pd.Series:
        return pd.Series([color_histogram(d, c) for d, c in zip(data, channels)])

    return (spark.read.format("image").load(folder)
            .filter("image.nChannels > 0")
            .select(F.col("_metadata.file_name").alias("file"),
                    histogram("image.data", "image.nChannels").alias("features")))


def audio_vectors(spark, folder=AUDIO):
    """One row per .wav file: file and features (array<float>, 16 values) from band_energies."""
    @F.pandas_udf("array<float>")
    def bands(content: pd.Series) -> pd.Series:
        return pd.Series([band_energies(c) for c in content])

    return (spark.read.format("binaryFile").option("pathGlobFilter", "*.wav").load(folder)
            .select(F.col("_metadata.file_name").alias("file"), bands("content").alias("features"))
            .filter("features IS NOT NULL"))


def with_unit_vectors(vectors):
    """Add unit (features scaled to length 1, array<float>, with vector_normalize)
    and vec (unit as an MLlib vector, with array_to_vector)."""
    return (vectors.withColumn("unit", F.call_function("vector_normalize", "features"))
            .withColumn("vec", array_to_vector("unit")))


def exact_neighbours(vectors):
    """For every file, its most similar other file: columns file, neighbour, cosine.

    Compare every pair (a self join without the pair of a file with itself),
    score with vector_cosine_similarity on `unit`, and keep the best per file;
    break ties by the neighbour's name so the result is repeatable.
    """
    a = vectors.select(F.col("file"), F.col("unit").alias("a"))
    b = vectors.select(F.col("file").alias("neighbour"), F.col("unit").alias("b"))
    pairs = (a.crossJoin(b).filter(F.col("file") != F.col("neighbour"))
             .select("file", "neighbour", F.call_function("vector_cosine_similarity", "a", "b").alias("cosine")))
    best = Window.partitionBy("file").orderBy(F.desc("cosine"), "neighbour")
    return pairs.withColumn("rank", F.row_number().over(best)).filter("rank = 1").drop("rank")


def lsh_candidates(vectors, bucket_length, num_tables, seed=42):
    """Every candidate pair LSH proposes: columns file, neighbour, distance.

    Fit BucketedRandomProjectionLSH on `vec` (inputCol "vec", outputCol
    "hashes"), then self-join with approxSimilarityJoin and a threshold of 2.0
    (no two unit vectors are further apart than that, so every candidate
    survives). Drop the pairs of a file with itself. Keep MLlib's default
    distance column name, distCol, and rename it with alias.
    """
    model = BucketedRandomProjectionLSH(inputCol="vec", outputCol="hashes", bucketLength=bucket_length,
                                        numHashTables=num_tables, seed=seed).fit(vectors)
    hashed = model.transform(vectors)
    return (model.approxSimilarityJoin(hashed, hashed, 2.0)
            .filter(F.col("datasetA.file") != F.col("datasetB.file"))
            .select(F.col("datasetA.file").alias("file"), F.col("datasetB.file").alias("neighbour"),
                    F.col("distCol").alias("distance")))


def lsh_neighbours(candidates):
    """The best candidate per file: columns file, neighbour, distance (smallest distance,
    ties broken by neighbour name). Files with no candidate are simply missing."""
    best = Window.partitionBy("file").orderBy("distance", "neighbour")
    return candidates.withColumn("rank", F.row_number().over(best)).filter("rank = 1").drop("rank")


def recall_at_1(vectors, exact, approx):
    """Fraction of files for which LSH found a neighbour as similar as the true best one.

    Join exact (file, neighbour, cosine) to approx (file, neighbour) on file
    (a left join: a file LSH found nothing for counts as a miss), compute the
    cosine between each file and its LSH neighbour with vector_cosine_similarity,
    and count it as found when that cosine >= the exact cosine - 1e-6 (a tie
    with a different file is still a correct answer). Return a float.
    """
    units = vectors.select("file", "unit")
    approx_cos = (approx.select("file", F.col("neighbour").alias("found"))
                  .join(units, "file")
                  .join(units.select(F.col("file").alias("found"), F.col("unit").alias("found_unit")), "found")
                  .select("file", F.call_function("vector_cosine_similarity", "unit", "found_unit").alias("found_cosine")))
    row = (exact.join(approx_cos, "file", "left")
           .agg(F.avg(F.coalesce(F.col("found_cosine") >= F.col("cosine") - 1e-6, F.lit(False))
                      .cast("double")).alias("recall"))
           .first())
    return float(row.recall)


# ---- Test harness ----
if __name__ == "__main__":
    import csv

    from pyspark.ml.linalg import VectorUDT

    spark = (SparkSession.builder
             .appName("SimilaritySearch")
             .master("local[*]")
             .config("spark.sql.shuffle.partitions", "4")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    with open(LABELS) as f:
        family = {r["file"]: r["family"] for r in csv.DictReader(f)}

    def numpy_neighbours(rows):
        """Exact nearest neighbours on the driver, as a reference."""
        names = [r.file for r in rows]
        m = np.array([np.asarray(r.features, dtype=np.float64) for r in rows])
        m = m / np.linalg.norm(m, axis=1, keepdims=True)
        sim = m @ m.T
        np.fill_diagonal(sim, -2)
        return {n: float(sim[i].max()) for i, n in enumerate(names)}

    try:
        # 1. Image vectors
        images = image_vectors(spark)
        assert images is not None, "image_vectors returned None"
        assert images.columns == ["file", "features"], f"Expected columns file, features; got {images.columns}"
        assert images.schema["features"].dataType.simpleString() == "array<float>", (
            f"features should be array<float> (the 4.2 vector_* functions need FLOAT), got "
            f"{images.schema['features'].dataType.simpleString()}")
        img_rows = images.collect()
        img_files = {r.file for r in img_rows}
        assert "thumbnail_cache.png" not in img_files, (
            "thumbnail_cache.png is not a real PNG; filter on image.nChannels > 0")
        assert len(img_rows) == 42, f"Expected 42 valid images, got {len(img_rows)}"
        for r in img_rows:
            assert r.features is not None and len(r.features) == 64, (
                f"{r.file}: expected 64 histogram values, got {None if r.features is None else len(r.features)}")
            assert abs(sum(r.features) - 1.0) < 1e-4, f"{r.file}: histogram should sum to 1, got {sum(r.features)}"
        by_file = {r.file: r.features for r in img_rows}
        assert by_file["checker_gray.png"] == by_file["checker_original.png"], (
            "The gray checkerboard should have the same histogram as the colour one; pass image.nChannels "
            "so color_histogram treats a 1-channel image as gray")
        red = by_file["mug_red_original.png"]
        assert red[3 * 16] > 0.1, (
            "The red mug should put pixels in the (red=3, green=0, blue=0) cell; pass image.data, which "
            "is B, G, R, unchanged to color_histogram")

        # 2. Audio vectors
        audio = audio_vectors(spark)
        assert audio is not None, "audio_vectors returned None"
        assert audio.columns == ["file", "features"], f"Expected columns file, features; got {audio.columns}"
        aud_rows = audio.collect()
        assert len(aud_rows) == 40, f"Expected 40 WAV clips, got {len(aud_rows)}"
        assert all(len(r.features) == 16 for r in aud_rows), "Every clip should have 16 band energies"

        # 3. Unit vectors
        units = {}
        for kind, df in [("image", images), ("audio", audio)]:
            u = with_unit_vectors(df)
            assert u is not None, "with_unit_vectors returned None"
            assert u.columns == ["file", "features", "unit", "vec"], (
                f"Expected columns file, features, unit, vec; got {u.columns}")
            assert isinstance(u.schema["vec"].dataType, VectorUDT), (
                f"vec should be an MLlib vector (array_to_vector), got {u.schema['vec'].dataType}")
            for r in u.select("unit").collect():
                assert abs(float(np.linalg.norm(np.asarray(r.unit))) - 1.0) < 1e-5, (
                    "unit should have length 1; use vector_normalize")
            units[kind] = u.cache()

        # 4. Exact neighbours
        exact = {}
        for kind, rows in [("image", img_rows), ("audio", aud_rows)]:
            ex = exact_neighbours(units[kind])
            assert ex is not None, "exact_neighbours returned None"
            assert ex.columns == ["file", "neighbour", "cosine"], (
                f"Expected columns file, neighbour, cosine; got {ex.columns}")
            got = {r.file: r for r in ex.collect()}
            want = numpy_neighbours(rows)
            assert len(got) == len(rows), f"{kind}: expected one neighbour per file ({len(rows)}), got {len(got)}"
            for f_, best in want.items():
                assert got[f_].neighbour != f_, f"{f_} is its own neighbour; drop the pair of a file with itself"
                assert abs(got[f_].cosine - best) < 1e-4, (
                    f"{kind} {f_}: the most similar file has cosine {best:.5f}, yours has {got[f_].cosine}")
            same = sum(family[f_] == family[r.neighbour] for f_, r in got.items())
            print(f"{kind}: nearest neighbour in the same family for {same} of {len(got)} files")
            exact[kind] = ex.cache()
        dup = exact["image"].filter("file = 'IMG_0042.png'").first()
        assert family[dup.neighbour] == "mug_red" and dup.cosine >= 0.9999, (
            f"IMG_0042.png is a byte-for-byte copy of mug_red_original.png, so its best cosine should be 1; "
            f"got {dup.neighbour} ({dup.cosine})")

        # 5. LSH: candidates, neighbours and recall
        results = {}
        for kind in ["image", "audio"]:
            n = units[kind].count()
            for bucket_length, tables in [(0.05, 1), (0.1, 5)]:
                cands = lsh_candidates(units[kind], bucket_length, tables)
                assert cands is not None, "lsh_candidates returned None"
                assert cands.columns == ["file", "neighbour", "distance"], (
                    f"Expected columns file, neighbour, distance; got {cands.columns}")
                cands = cands.cache()
                n_cands = cands.count()
                assert cands.filter("file = neighbour").count() == 0, "Drop the pairs of a file with itself"
                approx = lsh_neighbours(cands)
                assert approx is not None, "lsh_neighbours returned None"
                assert approx.columns == ["file", "neighbour", "distance"], (
                    f"lsh_neighbours: expected columns file, neighbour, distance; got {approx.columns}")
                assert approx.groupBy("file").count().filter("count > 1").count() == 0, (
                    "lsh_neighbours should keep one row per file")
                rec = recall_at_1(units[kind], exact[kind], approx)
                assert rec is not None, "recall_at_1 returned None"
                results[(kind, bucket_length, tables)] = (n_cands, n * (n - 1), rec)
                print(f"{kind}: bucketLength={bucket_length} tables={tables}: {n_cands} of {n * (n - 1)} "
                      f"ordered pairs compared, recall@1 = {rec:.3f}")
                cands.unpersist()
            weak = results[(kind, 0.05, 1)]
            strong = results[(kind, 0.1, 5)]
            assert weak[0] < strong[0], (
                f"{kind}: wider buckets and more tables should propose more candidates ({weak[0]} vs {strong[0]})")
            assert weak[2] < 1.0, f"{kind}: narrow buckets with one table should miss some neighbours, got {weak[2]}"
            assert strong[2] >= 0.95, (
                f"{kind}: bucketLength=0.1 with 5 tables should find at least 95% of the true neighbours, "
                f"got {strong[2]:.3f}")
            assert strong[0] < strong[1], f"{kind}: LSH should compare fewer pairs than the exact search"

        print()
        print("Images whose nearest neighbour is from another family:")
        labels = spark.read.option("header", True).csv(LABELS)
        (exact["image"].join(labels.select("file", "family"), "file")
         .join(labels.select(F.col("file").alias("neighbour"), F.col("family").alias("neighbour_family")), "neighbour")
         .filter("family != neighbour_family")
         .select("file", "neighbour", F.round("cosine", 3).alias("cosine")).show(truncate=False))
        print("All tests passed!")
    finally:
        spark.stop()
