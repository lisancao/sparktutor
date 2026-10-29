"""Sample data for "Production Ingestion: Quality Rules, Quarantine and Pipelines".

Writes out/quality/:

- customers.csv: 40 customers with planted problems (an e-mail without @, a
  blank e-mail, a blank country, month 13, and C017 listed twice).
- orders/orders_2026-10-01.csv and orders_2026-10-02.csv: 60 orders a day,
  with problems planted at fixed rows (blank and unknown customer keys, bad
  numbers, values outside the allowed sets, a status in the wrong case,
  duplicates within and across days, a timestamp in the future).
- incoming/orders_2026-10-03.csv: a third day from a broken export: most
  prices are blank. A quality gate should stop it.
- rules.json: the row-level rules for orders, as data.
"""
import csv
import json
import random
from pathlib import Path

STATUSES = ["placed", "placed", "placed", "shipped", "shipped", "cancelled", "returned"]
COUNTRIES = ["CA", "US", "VN"]
FIRST = ["Ana", "Binh", "Chloe", "Dev", "Emma", "Femi", "Grace", "Hoa", "Ivan", "Jade",
         "Kai", "Linh", "Mona", "Nam", "Omar", "Priya", "Quinn", "Rosa", "Sam", "Tuan"]
LAST = ["Nguyen", "Smith", "Tremblay", "Patel", "Garcia", "Tran", "Roy", "Kim", "Lee", "Martin"]


def generate(out: Path) -> None:
    rng = random.Random(1414)
    q = out / "quality"
    (q / "orders").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ customers
    customers = []
    for i in range(1, 41):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        customers.append({
            "customer_id": f"C{i:03d}",
            "name": f"{first} {last}",
            "email": f"{first.lower()}.{last.lower()}{i}@example.com",
            "country": rng.choice(COUNTRIES),
            "signup_date": f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
        })
    customers[4]["email"] = "emma.at.example.com"          # no @
    customers[22]["email"] = ""                             # blank email
    customers[9]["country"] = ""                            # blank country
    customers[30]["signup_date"] = "2025-13-01"             # month 13
    dup = dict(customers[16], email="new." + customers[16]["email"])
    customers.insert(17, dup)                               # C017 twice
    with open(q / "customers.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(customers[0]))
        w.writeheader()
        w.writerows(customers)

    # ------------------------------------------------------------ orders
    ids = [c["customer_id"] for c in customers]
    fields = ["order_id", "customer_id", "order_ts", "quantity", "unit_price", "status", "currency"]
    n = 0
    days = {}
    for day in ("2026-10-01", "2026-10-02"):
        rows = []
        for i in range(60):
            n += 1
            rows.append({
                "order_id": f"O{n:04d}",
                "customer_id": rng.choice(ids),
                "order_ts": f"{day} {8 + i // 6:02d}:{(i * 7) % 60:02d}:00",
                "quantity": str(rng.randint(1, 5)),
                "unit_price": f"{rng.uniform(3, 120):.2f}",
                "status": rng.choice(STATUSES),
                "currency": rng.choice(["CAD", "CAD", "USD"]),
            })
        days[day] = rows

    d1, d2 = days["2026-10-01"], days["2026-10-02"]
    # Problems on day 1
    d1[3]["customer_id"] = ""                 # missing key
    d1[11]["customer_id"] = "C099"            # unknown customer
    d1[18]["quantity"] = "0"                  # not positive
    d1[25]["unit_price"] = "N/A"              # not a number
    d1[31]["status"] = "SHIPPED"              # wrong case
    d1[40]["quantity"] = ""                   # missing quantity
    d1[47]["currency"] = "EUR"                # not an allowed currency
    # Problems on day 2
    d2[2]["customer_id"] = "C100"             # unknown customer
    d2[9]["quantity"] = "-2"                  # negative
    d2[14]["unit_price"] = ""                 # missing price
    d2[20]["status"] = "shiped"               # typo
    d2[26]["order_ts"] = "2027-01-15 09:00:00"  # in the future
    d2[33]["unit_price"] = "1,299.00"         # thousands separator
    d2[38]["customer_id"] = ""                # missing key
    d2[44]["quantity"] = "two"                # not a number
    # Duplicates: day 2 re-sends two day-1 orders, and repeats one of its own rows
    d2[50] = dict(d1[5])
    d2[51] = dict(d1[6])
    d2[52] = dict(d2[12])

    for day, rows in days.items():
        with open(q / "orders" / f"orders_{day}.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    # ------------------------------------------------------------ day 3: a broken export
    (q / "incoming").mkdir(exist_ok=True)
    d3 = []
    for i in range(60):
        n += 1
        d3.append({
            "order_id": f"O{n:04d}",
            "customer_id": rng.choice(ids[:40]),
            "order_ts": f"2026-10-03 {8 + i // 6:02d}:{(i * 7) % 60:02d}:00",
            "quantity": str(rng.randint(1, 5)),
            "unit_price": "" if i % 4 else f"{rng.uniform(3, 120):.2f}",   # 45 of 60 blank
            "status": rng.choice(STATUSES),
            "currency": rng.choice(["CAD", "CAD", "USD"]),
        })
    with open(q / "incoming" / "orders_2026-10-03.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(d3)

    # ------------------------------------------------------------ rules as data
    # severity "error": the row goes to quarantine; "warn": the row is kept
    # (after normalizing) and counted.
    rules = [
        {"name": "order_id_present", "severity": "error",
         "check": "order_id IS NOT NULL AND trim(order_id) <> ''"},
        {"name": "customer_id_present", "severity": "error",
         "check": "customer_id IS NOT NULL AND trim(customer_id) <> ''"},
        {"name": "quantity_is_integer", "severity": "error",
         "check": "try_cast(quantity AS INT) IS NOT NULL"},
        {"name": "quantity_positive", "severity": "error",
         "check": "try_cast(quantity AS INT) > 0"},
        {"name": "unit_price_is_number", "severity": "error",
         "check": "try_cast(unit_price AS DECIMAL(10,2)) IS NOT NULL"},
        {"name": "status_allowed", "severity": "error",
         "check": "lower(trim(status)) IN ('placed', 'shipped', 'cancelled', 'returned')"},
        {"name": "status_lowercase", "severity": "warn",
         "check": "status = lower(trim(status))"},
        {"name": "currency_allowed", "severity": "error",
         "check": "currency IN ('CAD', 'USD')"},
        {"name": "order_ts_valid", "severity": "error",
         "check": "try_to_timestamp(order_ts) IS NOT NULL"},
        # The two rules below use columns the ingestion job adds: _file_date
        # (the business date in the file name) and _customer_known (from a
        # left join against the customers).
        {"name": "order_ts_not_after_file_day", "severity": "error",
         "check": "to_date(try_to_timestamp(order_ts)) <= _file_date"},
        {"name": "customer_known", "severity": "error",
         "check": "_customer_known"},
    ]
    (q / "rules.json").write_text(json.dumps(rules, indent=2) + "\n")
