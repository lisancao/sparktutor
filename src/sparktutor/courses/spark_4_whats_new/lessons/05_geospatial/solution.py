"""
Geospatial Types - Solution

Store points as GEOGRAPHY/GEOMETRY, round-trip them through Parquet,
and find each customer's nearest store.
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

    # 1. GEOGRAPHY from Python objects: Geography(wkb, srid) with GeographyType(4326).
    schema = StructType([
        StructField("store", StringType()),
        StructField("loc", GeographyType(4326)),
    ])
    stores = spark.createDataFrame(
        [(name, Geography.fromWKB(point_wkb(lon, lat), 4326)) for name, lon, lat in STORES],
        schema,
    )

    # 2. Parquet round trip (Parquet read/write for geo types is new in 4.2).
    path = f"{workdir}/stores"
    stores.write.mode("overwrite").parquet(path)
    stores_back = spark.read.parquet(path)

    # 3. GEOMETRY from WKB in SQL, in a projected CRS (Web Mercator, SRID 3857).
    projected = spark.createDataFrame(
        [(name, bytearray(point_wkb(*to_web_mercator(lon, lat)))) for name, lon, lat in STORES],
        "store string, wkb binary",
    ).select("store", sf.st_geomfromwkb("wkb", sf.lit(3857)).alias("geom"))

    # 4. Nearest store per customer: cross join, distance UDF on WKB bytes,
    #    keep rank 1 with QUALIFY.
    customers = spark.createDataFrame(
        [(name, Geography.fromWKB(point_wkb(lon, lat), 4326)) for name, lon, lat in CUSTOMERS],
        StructType([StructField("customer", StringType()), StructField("loc", GeographyType(4326))]),
    )
    stores_back.createOrReplaceTempView("stores")
    customers.createOrReplaceTempView("customers")
    spark.udf.register("haversine_km", haversine_km)
    nearest = spark.sql("""
        SELECT c.customer, s.store,
               round(haversine_km(st_asbinary(c.loc), st_asbinary(s.loc)), 2) AS km
        FROM customers c CROSS JOIN stores s
        QUALIFY row_number() OVER (PARTITION BY c.customer ORDER BY km) = 1
        ORDER BY c.customer
    """)

    srids = {r["s"] for r in stores_back.select(sf.st_srid("loc").alias("s")).collect()}

    return {
        "stores_back": stores_back,
        "srids": srids,
        "projected": projected,
        "nearest": nearest,
    }


# ---- Test harness ----
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
