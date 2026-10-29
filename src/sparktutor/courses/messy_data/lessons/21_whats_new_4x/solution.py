"""
What Spark 4.x Adds for Messy Data - Solution

Clean courier coordinates (swapped, out of range, null island, NaN, blanks),
turn them into GEOGRAPHY(4326) values through WKB, find each delivery's
nearest store with a grid bucket and a haversine distance built from SQL
functions, tag delivery zones with a point-in-polygon UDF, and group messy
city names with a collation.
"""

import math
import struct

from pyspark.sql import SparkSession, Window, functions as F

STORES = "data/messy/geo_deliveries/stores.csv"
DELIVERIES = "data/messy/geo_deliveries/deliveries.csv"

# Where the company delivers: (name, lat_min, lat_max, lon_min, lon_max)
SERVICE_AREAS = [
    ("Canada", 41.0, 84.0, -142.0, -52.0),
    ("Vietnam", 8.0, 24.0, 102.0, 110.0),
]

# Delivery zones as closed rings of (lon, lat), x before y like WKB
ZONES = {
    # an L shape: downtown plus the West End, not the water in the corner
    "Downtown Vancouver": [(-123.15, 49.26), (-123.07, 49.26), (-123.07, 49.29),
                           (-123.11, 49.29), (-123.11, 49.31), (-123.15, 49.31),
                           (-123.15, 49.26)],
    "Old Quarter": [(105.82, 21.00), (105.88, 21.00), (105.88, 21.06),
                    (105.82, 21.06), (105.82, 21.00)],
}

EARTH_RADIUS_KM = 6371.0


# ---- Helpers (given) ----

def read_csv(spark, path):
    """Read a CSV with a header, every column as a string."""
    return spark.read.option("header", True).option("inferSchema", False).csv(path)


def point_wkb(lon, lat):
    """A 2D point as little-endian WKB: byte order 1, type 1 (Point), x, y."""
    if lon is None or lat is None:
        return None
    return struct.pack("<BIdd", 1, 1, lon, lat)


def point_from_wkb(wkb):
    """(lon, lat) from a WKB point in either byte order."""
    if wkb is None:
        return None
    wkb = bytes(wkb)
    order = "<" if wkb[0] == 1 else ">"
    kind, = struct.unpack(order + "I", wkb[1:5])
    if kind != 1:
        raise ValueError(f"not a point: WKB type {kind}")
    return struct.unpack(order + "dd", wkb[5:21])


def point_in_ring(lon, lat, ring):
    """Ray casting: is (lon, lat) inside the closed ring? Points on an edge may go either way."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat):
            x_cross = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_cross:
                inside = not inside
    return inside


def in_area(lat, lon):
    """Column expression: true when (lat, lon) falls in one of the SERVICE_AREAS."""
    cond = F.lit(False)
    for _, lat_min, lat_max, lon_min, lon_max in SERVICE_AREAS:
        cond = cond | (lat.between(lat_min, lat_max) & lon.between(lon_min, lon_max))
    return cond


# ---- Your code ----

def clean_points(raw):
    """Typed, validated coordinates: delivery_id, city, lat, lon, status.

    Rules, in this order:
      missing       lat or lon is NULL or blank after trimming
      unparseable   lat or lon does not parse as a double, or is NaN
      null_island   both are 0
      ok            (lat, lon) is in a service area
      swapped       (lon, lat) is in a service area: swap them back
      outside_area  valid ranges (lat in [-90, 90], lon in [-180, 180]) but no service area
      out_of_range  anything else
    lat and lon are doubles for ok and swapped rows (swapped rows fixed), NULL otherwise.
    """
    lat_s, lon_s = F.trim("lat"), F.trim("lon")
    lat, lon = lat_s.try_cast("double"), lon_s.try_cast("double")
    status = (F.when(lat_s.isNull() | lon_s.isNull() | (lat_s == "") | (lon_s == ""), "missing")
        .when(lat.isNull() | lon.isNull() | F.isnan(lat) | F.isnan(lon), "unparseable")
        .when((lat == 0) & (lon == 0), "null_island")
        .when(in_area(lat, lon), "ok")
        .when(in_area(lon, lat), "swapped")
        .when(lat.between(-90, 90) & lon.between(-180, 180), "outside_area")
        .otherwise("out_of_range"))
    typed = raw.select("delivery_id", "city", lat.alias("lat_d"), lon.alias("lon_d"), status.alias("status"))
    return typed.select(
        "delivery_id", "city",
        F.when(F.col("status") == "ok", F.col("lat_d"))
         .when(F.col("status") == "swapped", F.col("lon_d")).alias("lat"),
        F.when(F.col("status") == "ok", F.col("lon_d"))
         .when(F.col("status") == "swapped", F.col("lat_d")).alias("lon"),
        "status")


def with_geography(points):
    """Add wkb (BINARY, from point_wkb) and geo (GEOGRAPHY(4326), from st_geogfromwkb).

    Both are NULL where lat or lon is NULL. Create the UDF inside this function.
    """
    to_wkb = F.udf(point_wkb, "binary")
    return (points.withColumn("wkb", to_wkb("lon", "lat"))
                  .withColumn("geo", F.st_geogfromwkb("wkb")))


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between two points given as Column expressions, built-ins only."""
    dlat = F.radians(lat2 - lat1)
    dlon = F.radians(lon2 - lon1)
    a = (F.pow(F.sin(dlat / 2), 2)
         + F.cos(F.radians(lat1)) * F.cos(F.radians(lat2)) * F.pow(F.sin(dlon / 2), 2))
    return 2 * EARTH_RADIUS_KM * F.asin(F.sqrt(a))


def nearest_store(points, stores, cell_deg):
    """For every point with coordinates: delivery_id, store_id, km.

    Only stores in the same grid cell or one of the 8 neighbouring cells are
    candidates (cell = floor(lat / cell_deg), floor(lon / cell_deg)). store_id
    and km are NULL when no store is a candidate.
    """
    pts = (points.filter(F.col("lat").isNotNull())
        .select("delivery_id", "lat", "lon",
                F.floor(F.col("lat") / cell_deg).alias("cell_lat"),
                F.floor(F.col("lon") / cell_deg).alias("cell_lon")))
    offsets = F.sequence(F.lit(-1), F.lit(1))
    cand = (stores.select("store_id",
                          F.col("lat").cast("double").alias("s_lat"),
                          F.col("lon").cast("double").alias("s_lon"))
        .withColumn("dlat", F.explode(offsets))
        .withColumn("dlon", F.explode(offsets))
        .select("store_id", "s_lat", "s_lon",
                (F.floor(F.col("s_lat") / cell_deg) + F.col("dlat")).alias("cell_lat"),
                (F.floor(F.col("s_lon") / cell_deg) + F.col("dlon")).alias("cell_lon")))
    pairs = (pts.join(cand, ["cell_lat", "cell_lon"], "left")
        .withColumn("km", haversine_km(F.col("lat"), F.col("lon"), F.col("s_lat"), F.col("s_lon"))))
    best = Window.partitionBy("delivery_id").orderBy(F.col("km").asc_nulls_last(), "store_id")
    return (pairs.withColumn("rank", F.row_number().over(best))
        .filter("rank = 1")
        .select("delivery_id", "store_id", "km"))


def zone_of(geo_points):
    """delivery_id and zone (the ZONES name containing the point, or NULL) for rows with a geo.

    Use a Python UDF over st_asbinary(geo), point_from_wkb and point_in_ring.
    """
    def find_zone(wkb):
        if wkb is None:
            return None
        lon, lat = point_from_wkb(wkb)
        for name, ring in ZONES.items():
            if point_in_ring(lon, lat, ring):
                return name
        return None

    zone = F.udf(find_zone, "string")
    return (geo_points.filter(F.col("geo").isNotNull())
        .select("delivery_id", zone(F.st_asbinary("geo")).alias("zone")))


def city_groups(raw, stores):
    """Group the raw delivery city names that mean the same city.

    Two names are the same city when they are equal after trimming spaces at
    both ends, ignoring case and accents (collation UNICODE_CI_AI). Return:
      city      the matching city name from stores.csv, or NULL if no store city matches
      n         number of deliveries in the group
      variants  the distinct raw spellings in the group, sorted
    """
    key = F.collate(F.trim("city"), "UNICODE_CI_AI")
    groups = (raw.groupBy(key.alias("key"))
        .agg(F.count("*").alias("n"), F.sort_array(F.collect_set("city")).alias("variants")))
    store_cities = stores.select(F.col("city").alias("store_city")).distinct()
    joined = groups.join(store_cities,
                         groups.key == F.collate(F.col("store_city"), "UNICODE_CI_AI"), "left")
    return joined.select(F.col("store_city").alias("city"), "n", "variants")


# ---- Test harness ----
if __name__ == "__main__":
    import csv
    import unicodedata

    from pyspark.sql.types import GeographyType

    spark = (SparkSession.builder
        .appName("WhatsNew4x")
        .master("local[*]")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    def py_float(s):
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    def py_in_area(lat, lon):
        return any(a <= lat <= b and c <= lon <= d for _, a, b, c, d in SERVICE_AREAS)

    def py_clean(lat_s, lon_s):
        lat_s, lon_s = (lat_s or "").strip(), (lon_s or "").strip()
        if not lat_s or not lon_s:
            return None, None, "missing"
        lat, lon = py_float(lat_s), py_float(lon_s)
        if lat is None or lon is None or math.isnan(lat) or math.isnan(lon):
            return None, None, "unparseable"
        if lat == 0 and lon == 0:
            return None, None, "null_island"
        if py_in_area(lat, lon):
            return lat, lon, "ok"
        if py_in_area(lon, lat):
            return lon, lat, "swapped"
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return None, None, "outside_area"
        return None, None, "out_of_range"

    def py_haversine(lat1, lon1, lat2, lon2):
        dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
        return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))

    def py_city_key(name):
        s = unicodedata.normalize("NFKD", name.strip().casefold())
        return "".join(c for c in s if not unicodedata.combining(c)).replace("đ", "d")

    with open(DELIVERIES, encoding="utf-8") as f:
        raw_rows = list(csv.DictReader(f))
    with open(STORES, encoding="utf-8") as f:
        store_rows = list(csv.DictReader(f))
    expected = {r["delivery_id"]: py_clean(r["lat"], r["lon"]) for r in raw_rows}

    try:
        raw = read_csv(spark, DELIVERIES)
        stores = read_csv(spark, STORES)

        # 1. Cleaning
        points = clean_points(raw)
        assert points is not None, "clean_points returned None"
        assert points.columns == ["delivery_id", "city", "lat", "lon", "status"], (
            f"Expected columns delivery_id, city, lat, lon, status; got {points.columns}")
        assert dict(points.dtypes)["lat"] == "double" and dict(points.dtypes)["lon"] == "double", (
            f"lat and lon should be doubles, got {points.dtypes}")
        got = {r.delivery_id: (r.lat, r.lon, r.status) for r in points.collect()}
        assert len(got) == len(expected), f"Expected {len(expected)} deliveries, got {len(got)}"
        for did, (lat, lon, status) in sorted(expected.items()):
            g = got[did]
            assert g[2] == status, (
                f"{did} (lat={next(r['lat'] for r in raw_rows if r['delivery_id'] == did)!r}, "
                f"lon={next(r['lon'] for r in raw_rows if r['delivery_id'] == did)!r}): "
                f"expected status {status}, got {g[2]}. Check the order of the rules")
            if lat is None:
                assert g[0] is None and g[1] is None, f"{did} is {status}: lat and lon should be NULL, got {g[:2]}"
            else:
                assert g[0] is not None and abs(g[0] - lat) < 1e-9 and abs(g[1] - lon) < 1e-9, (
                    f"{did} is {status}: expected lat={lat}, lon={lon}, got {g[:2]}")
        statuses = {s for _, _, s in expected.values()}
        assert statuses == {"ok", "swapped", "outside_area", "out_of_range", "null_island",
                            "missing", "unparseable"}, f"Sample data changed? statuses {statuses}"

        # 2. WKB and GEOGRAPHY
        geo_points = with_geography(points)
        assert geo_points is not None, "with_geography returned None"
        geo_type = geo_points.schema["geo"].dataType
        assert isinstance(geo_type, GeographyType) and geo_type.srid == 4326, (
            f"geo should be GEOGRAPHY(4326), got {geo_type}")
        rows = geo_points.select("delivery_id", "wkb", F.st_asbinary("geo").alias("back"),
                                 F.st_srid("geo").alias("srid"), "geo").collect()
        for r in rows:
            lat, lon, _ = expected[r.delivery_id]
            if lat is None:
                assert r.wkb is None and r.back is None, f"{r.delivery_id}: wkb and geo should be NULL"
            else:
                assert bytes(r.wkb) == point_wkb(lon, lat), (
                    f"{r.delivery_id}: wkb should be point_wkb(lon, lat): longitude first")
                assert bytes(r.back) == bytes(r.wkb) and r.srid == 4326, (
                    f"{r.delivery_id}: st_asbinary(geo) should give back the same WKB with SRID 4326")
                assert r.geo.getSrid() == 4326, "Collected geo values should be Geography objects with SRID 4326"

        # 3. Nearest store within the 3 x 3 grid neighbourhood
        cell = 0.1
        near = nearest_store(geo_points, stores, cell)
        assert near is not None, "nearest_store returned None"
        assert near.columns == ["delivery_id", "store_id", "km"], (
            f"Expected columns delivery_id, store_id, km; got {near.columns}")
        got_near = {r.delivery_id: (r.store_id, r.km) for r in near.collect()}
        with_coords = {d: v for d, v in expected.items() if v[0] is not None}
        assert set(got_near) == set(with_coords), (
            f"Expected one row per delivery with coordinates ({len(with_coords)}), got {len(got_near)}. "
            "Deliveries with no store nearby need a row too: use a left join")
        no_store = 0
        for did, (lat, lon, _) in with_coords.items():
            cands = [(py_haversine(lat, lon, float(s["lat"]), float(s["lon"])), s["store_id"])
                     for s in store_rows
                     if abs(math.floor(lat / cell) - math.floor(float(s["lat"]) / cell)) <= 1
                     and abs(math.floor(lon / cell) - math.floor(float(s["lon"]) / cell)) <= 1]
            want = min(cands) if cands else (None, None)
            store, km = got_near[did]
            if want[1] is None:
                no_store += 1
                assert store is None and km is None, (
                    f"{did} has no store in its neighbourhood: store_id and km should be NULL, got {store}")
            else:
                assert store == want[1] and abs(km - want[0]) < 1e-6, (
                    f"{did}: expected nearest {want[1]} at {want[0]:.3f} km, got {store} at {km}")
        assert no_store >= 6, "The six deliveries in Ottawa, Calgary and Hue have no store nearby"

        # 4. Zones
        zones = zone_of(geo_points)
        assert zones is not None, "zone_of returned None"
        got_zone = {r.delivery_id: r.zone for r in zones.collect()}
        assert set(got_zone) == set(with_coords), "zone_of should return every delivery with a geo"
        for did, (lat, lon, _) in with_coords.items():
            want = next((n for n, ring in ZONES.items() if point_in_ring(lon, lat, ring)), None)
            assert got_zone[did] == want, f"{did} at ({lat}, {lon}): expected zone {want}, got {got_zone[did]}"
        in_zone = sum(1 for z in got_zone.values() if z)

        # 5. City names
        groups = city_groups(raw, stores)
        assert groups is not None, "city_groups returned None"
        assert groups.columns == ["city", "n", "variants"], (
            f"Expected columns city, n, variants; got {groups.columns}")
        got_groups = {frozenset(r.variants): (r.city, r.n) for r in groups.collect()}
        want_groups = {}
        for r in raw_rows:
            want_groups.setdefault(py_city_key(r["city"]), []).append(r["city"])
        store_city = {py_city_key(s["city"]): s["city"] for s in store_rows}
        want = {frozenset(v): (store_city.get(k), len(v)) for k, v in want_groups.items()}
        assert len(got_groups) == len(want), (
            f"Expected {len(want)} city groups, got {len(got_groups)}. Trim both ends before "
            "collating, and use a case- and accent-insensitive collation. Your groups: "
            f"{sorted(sorted(v) for v in got_groups)}")
        assert got_groups == want, f"City groups differ: expected {want}, got {got_groups}"

        counts = {}
        for _, _, s in expected.values():
            counts[s] = counts.get(s, 0) + 1
        print("Statuses:", dict(sorted(counts.items())))
        print(f"Deliveries with no store nearby: {no_store}; in a zone: {in_zone}")
        near.join(points.select("delivery_id", "city"), "delivery_id").orderBy("delivery_id").show(5)
        groups.orderBy(F.col("n").desc()).show(truncate=False)
        print("All tests passed!")
    finally:
        spark.stop()
