"""
Geospatial Types - Starter Code

Implement `build_store_locator(spark, workdir)`. It must:
1. Build a `stores` DataFrame (store string, loc GEOGRAPHY(4326)) from
   Geography.fromWKB(point_wkb(lon, lat), 4326) values
2. Write it to Parquet at f"{workdir}/stores" and read it back
3. Build `projected` (store, geom GEOMETRY(3857)) with st_geomfromwkb over
   Web Mercator WKB built from to_web_mercator(lon, lat)
4. Find each customer's nearest store: cross join customers and stores,
   compute haversine_km(st_asbinary(c.loc), st_asbinary(s.loc)) rounded to
   2 decimals AS km, keep the closest per customer with QUALIFY
"""

import math
import struct
import tempfile

from pyspark.sql import SparkSession, functions as sf
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, GeographyType, Geography,
)


STORES = [
    ("downtown", -123.1207, 49.2827),
    ("kitsilano", -123.1553, 49.2684),
    ("burnaby", -122.9805, 49.2488),
]

CUSTOMERS = [
    ("cust_a", -123.1180, 49.2800),
    ("cust_b", -122.9900, 49.2500),
    ("cust_c", -123.1600, 49.2650),
]


def point_wkb(lon, lat):
    """Little-endian WKB for a 2D point: byte order, geometry type 1, x, y."""
    return struct.pack("<BIdd", 1, 1, lon, lat)


def to_web_mercator(lon, lat):
    """Project lon/lat degrees to EPSG:3857 metres."""
    r = 6378137.0
    x = math.radians(lon) * r
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * r
    return x, y


@sf.udf(DoubleType())
def haversine_km(wkb_a, wkb_b):
    """Great-circle distance between two WKB points (no ST_Distance in 4.2)."""
    lon1, lat1 = struct.unpack("<dd", bytes(wkb_a)[5:21])
    lon2, lat2 = struct.unpack("<dd", bytes(wkb_b)[5:21])
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def build_store_locator(spark, workdir):
    """Return Parquet-round-tripped stores, a projected GEOMETRY table and nearest stores."""

    # TODO 1: schema with StructField("loc", GeographyType(4326)) and
    #         createDataFrame([(name, Geography.fromWKB(point_wkb(lon, lat), 4326)), ...], schema)
    stores = None  # Replace

    # TODO 2: write stores to Parquet under workdir and read it back
    stores_back = None  # Replace

    # TODO 3: DataFrame of (store, bytearray(point_wkb(*to_web_mercator(lon, lat))))
    #         as "store string, wkb binary", then
    #         select("store", sf.st_geomfromwkb("wkb", sf.lit(3857)).alias("geom"))
    projected = None  # Replace

    # TODO 4: customers DataFrame (customer, loc GEOGRAPHY(4326)); register temp
    #         views "stores" (from stores_back) and "customers";
    #         spark.udf.register("haversine_km", haversine_km); then a SQL query
    #         with CROSS JOIN, round(haversine_km(...), 2) AS km and QUALIFY
    nearest = None  # Replace

    # TODO: set of SRIDs in stores_back (via sf.st_srid)
    srids = None  # Replace

    return {
        "stores_back": stores_back,
        "srids": srids,
        "projected": projected,
        "nearest": nearest,
    }


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("GeospatialTest")
        .master("local[*]")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate())

    workdir = tempfile.mkdtemp(prefix="sparktutor_geo_")
    result = build_store_locator(spark, workdir)
    assert result is not None, "Function returned None"
    assert result["stores_back"].schema["loc"].dataType == GeographyType(4326), \
        f"Parquet should preserve GEOGRAPHY(4326), got {result['stores_back'].schema['loc'].dataType}"
    assert result["srids"] == {4326}, f"Unexpected SRIDs: {result['srids']}"
    proj = result["projected"]
    assert proj.schema["geom"].dataType.simpleString() == "geometry(3857)", proj.schema["geom"].dataType
    first = proj.select(sf.st_srid("geom").alias("s")).first()["s"]
    assert first == 3857
    nearest = {r["customer"]: (r["store"], r["km"]) for r in result["nearest"].collect()}
    assert {k: v[0] for k, v in nearest.items()} == {
        "cust_a": "downtown", "cust_b": "burnaby", "cust_c": "kitsilano"
    }, nearest
    assert all(v[1] < 2.0 for v in nearest.values()), nearest
    result["stores_back"].select("store", sf.st_srid("loc").alias("srid"),
                                 sf.hex(sf.st_asbinary("loc")).alias("wkb_hex")).show(truncate=False)
    result["nearest"].show()
    print("All tests passed!")
    spark.stop()
