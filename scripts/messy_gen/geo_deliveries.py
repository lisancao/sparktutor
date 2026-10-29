"""Sample data for "What Spark 4.x Adds for Messy Data".

Writes out/geo_deliveries/:
  stores.csv      store_id, name, city, lat, lon (clean, decimal degrees)
  deliveries.csv  delivery_id, city, lat, lon as typed by couriers and apps

The deliveries are messy on purpose: city names in several spellings (case,
accents, decomposed Unicode, leading and trailing spaces), coordinates with
stray spaces, latitude and longitude swapped, a slipped decimal point (out of
range), a lost minus sign (valid but outside the service area),
"null island" (0, 0), NaN, unparseable text, blanks, and a few deliveries far
from every store.
"""
import csv
import random
import unicodedata
from pathlib import Path

# (store_id, name, city, lat, lon)
STORES = [
    ("S01", "Gastown", "Vancouver", 49.2840, -123.1090),
    ("S02", "Kitsilano", "Vancouver", 49.2680, -123.1680),
    ("S03", "Metrotown", "Vancouver", 49.2270, -123.0000),
    ("S04", "Plateau", "Montréal", 45.5220, -73.5800),
    ("S05", "Verdun", "Montréal", 45.4580, -73.5700),
    ("S06", "Queen West", "Toronto", 43.6480, -79.4000),
    ("S07", "North York", "Toronto", 43.7610, -79.4110),
    ("S08", "Hoàn Kiếm", "Hà Nội", 21.0285, 105.8542),
    ("S09", "Cầu Giấy", "Hà Nội", 21.0333, 105.7950),
    ("S10", "Bến Thành", "Hồ Chí Minh", 10.7725, 106.6980),
    ("S11", "Thảo Điền", "Hồ Chí Minh", 10.8030, 106.7350),
    ("S12", "Hải Châu", "Đà Nẵng", 16.0600, 108.2200),
]

SPELLINGS = {
    "Vancouver": ["Vancouver", "VANCOUVER", "vancouver ", " Vancouver", "Vancouver  "],
    "Montréal": ["Montréal", "Montreal", "MONTRÉAL", "montreal ", "Montréal"],
    "Toronto": ["Toronto", "TORONTO", "toronto", " Toronto "],
    "Hà Nội": ["Hà Nội", "Ha Noi", "HÀ NỘI", "ha noi", unicodedata.normalize("NFD", "Hà Nội")],
    "Hồ Chí Minh": ["Hồ Chí Minh", "Ho Chi Minh", "HỒ CHÍ MINH", "ho chi minh "],
    "Đà Nẵng": ["Đà Nẵng", "Da Nang", "ĐÀ NẴNG", "da nang"],
}

# Places with no store nearby (they should find no nearest store)
FAR = [("Ottawa", 45.4215, -75.6972), ("Calgary", 51.0447, -114.0719), ("Huế", 16.4637, 107.5909)]


def fmt(rng, x):
    s = f"{x:.5f}"
    return rng.choice([s, s, s, f" {s}", f"{s} "])


def generate(out: Path) -> None:
    rng = random.Random(2121)
    base = out / "geo_deliveries"
    base.mkdir(parents=True, exist_ok=True)

    with open(base / "stores.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["store_id", "name", "city", "lat", "lon"])
        for row in STORES:
            w.writerow([row[0], row[1], row[2], f"{row[3]:.4f}", f"{row[4]:.4f}"])

    rows = []
    for i in range(1, 161):
        store = rng.choice(STORES)
        city = rng.choice(SPELLINGS[store[2]])
        # within roughly 6 km of the chosen store
        lat = store[3] + rng.uniform(-0.05, 0.05)
        lon = store[4] + rng.uniform(-0.05, 0.05)
        roll = rng.random()
        if i % 40 == 0:
            lat_s, lon_s = fmt(rng, lat), fmt(rng, -lon)             # a lost minus sign: outside the area
        elif i % 53 == 0:
            lat_s, lon_s = "NaN", fmt(rng, lon)                      # NaN parses as a double
        elif roll < 0.10:
            lat_s, lon_s = fmt(rng, lon), fmt(rng, lat)              # swapped
        elif roll < 0.13:
            lat_s, lon_s = fmt(rng, lat), fmt(rng, lon * 10)         # a slipped decimal point: out of range
        elif roll < 0.17:
            lat_s, lon_s = "0", "0"                                  # null island
        elif roll < 0.20:
            lat_s, lon_s = rng.choice([("", ""), ("", fmt(rng, lon)), (fmt(rng, lat), "")])
        elif roll < 0.23:
            lat_s, lon_s = rng.choice([("n/a", "n/a"), (f"{lat:.4f}N", f"{-lon:.4f}W"), ("NaN", "NaN")])
        else:
            lat_s, lon_s = fmt(rng, lat), fmt(rng, lon)
        rows.append([f"D{i:03d}", city, lat_s, lon_s])
    for j, (city, lat, lon) in enumerate(FAR):
        for k in range(2):
            rows.append([f"D{161 + 2 * j + k:03d}", city,
                         fmt(rng, lat + rng.uniform(-0.02, 0.02)), fmt(rng, lon + rng.uniform(-0.02, 0.02))])

    with open(base / "deliveries.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["delivery_id", "city", "lat", "lon"])
        w.writerows(rows)
