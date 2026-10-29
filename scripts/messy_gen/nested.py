"""Sample data for "Complex Types and Higher-Order Functions".

Writes out/nested/orders.json: web shop orders as JSON Lines, nested a few
levels deep (customer -> address -> geo, lines -> discounts, a free-form
attrs object per line, payments, a status history), with the problems real
nested data has planted at fixed orders:

- tags in mixed case, with spaces, duplicates and a null element; some
  orders have no tags key at all, some have an empty list
- one order with an empty lines list and one with no lines key
- attrs objects whose keys differ from line to line (a map, not a struct)
- country codes in mixed case
- status history entries out of time order
- a line with qty null
"""
import json
import random
from pathlib import Path

SKUS = {"P1": 4.5, "P2": 12.0, "P3": 7.25, "P4": 19.99, "P5": 2.5, "P6": 30.0}
CITIES = [("Toronto", "ca"), ("Montreal", "CA"), ("Hanoi", "vn"), ("Seattle", "US"),
          ("Vancouver", "Ca"), ("Da Nang", "VN"), ("Boston", "us")]
NAMES = ["Linh Tran", "Sam Roy", "Priya Patel", "Omar Kim", "Ana Garcia", "Kai Lee"]
TAGS = ["gift", "Gift", " rush ", "RUSH", "b2b", "fragile", "gift "]
ATTR_KEYS = {"color": ["red", "blue", "black"], "size": ["S", "M", "L"],
             "engraving": ["L.T.", "Happy 30th"], "gift_wrap": ["yes"],
             "warranty_years": ["1", "2"]}
STATUSES = ["placed", "paid", "shipped", "delivered"]


def generate(out: Path) -> None:
    rng = random.Random(909)
    folder = out / "nested"
    folder.mkdir(parents=True, exist_ok=True)

    orders = []
    for i in range(24):
        city, country = CITIES[i % len(CITIES)]
        lines = []
        for _ in range(rng.randint(1, 4)):
            sku = rng.choice(sorted(SKUS))
            attrs = {k: rng.choice(v) for k, v in ATTR_KEYS.items() if rng.random() < 0.35}
            discounts = [{"code": "FALL10", "pct": 10}] if rng.random() < 0.3 else []
            if rng.random() < 0.15:
                discounts.append({"code": "VIP5", "pct": 5})
            lines.append({"sku": sku, "qty": rng.randint(1, 5), "unit_price": SKUS[sku],
                          "discounts": discounts, "attrs": attrs})
        hour = 8 + i % 10
        history = [{"status": s, "at": f"2026-10-{5 + i % 3:02d}T{hour + k:02d}:{(7 * i) % 60:02d}:00"}
                   for k, s in enumerate(STATUSES[:rng.randint(1, 4)])]
        order = {
            "order_id": f"O-{1001 + i}",
            "placed_at": history[0]["at"],
            "customer": {
                "id": f"C{rng.randint(1, 9)}",
                "name": NAMES[i % len(NAMES)],
                "email": f"user{i}@example.com",
                "address": {"city": city, "country": country,
                            "geo": {"lat": round(rng.uniform(10, 50), 4),
                                    "lon": round(rng.uniform(-125, 110), 4)}},
            },
            "lines": lines,
            "tags": rng.sample(TAGS, rng.randint(0, 3)),
            "payments": [{"method": "card", "amount": round(sum(l["qty"] * l["unit_price"] for l in lines), 2)}],
            "status_history": history,
        }
        orders.append(order)

    # Planted problems at fixed orders
    orders[2]["tags"] = ["Gift", "gift", " GIFT", None, "rush"]   # case, spaces, dups, a null
    del orders[3]["tags"]                                           # no tags key
    orders[4]["tags"] = []                                          # empty list
    orders[5]["lines"] = []                                         # an order with no lines
    orders[5]["payments"] = []
    del orders[6]["lines"]                                          # lines key missing
    orders[6]["payments"] = []
    orders[7]["lines"][0]["qty"] = None                             # unknown quantity
    for k in (1, 8, 13, 19):                                        # history out of order
        orders[k]["status_history"].reverse()
    del orders[10]["customer"]["address"]["geo"]                    # no coordinates
    orders[11]["customer"]["email"] = None

    with open(folder / "orders.json", "w") as f:
        for o in orders:
            f.write(json.dumps(o) + "\n")
