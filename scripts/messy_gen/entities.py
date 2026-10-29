"""Sample data for "Deduplication and Entity Resolution".

Writes out/entities/: the same customers as three systems recorded them,
plus the answer key.

- crm.csv: the CRM export (crm_id, first_name, last_name, email, phone,
  city, updated_at). A few customers were entered twice.
- shop.csv: the web shop's customer table (customer_no, name, email,
  phone, city, last_order). Names are one field, sometimes "Last, First".
- support.jsonl: contacts from the support desk, JSON Lines (contact_id,
  name, email, phone, seen). seen is a timestamp.
- truth.csv: source, record_id, entity_id for every record: which real
  person each record belongs to. Use it only to evaluate.

Every record is a noisy copy of one true person: nicknames (Robert and
Bob), typos, missing accents, upper and lower case, Vietnamese names in
both orders, "Last, First", e-mails in other cases or with Gmail dots and
plus tags, phones in four formats, missing values, and people who moved
city. Hard cases are planted on purpose: different people who share a
full name, and family members who share a phone number, a surname and a
city but not a first name or an e-mail.
"""
import csv
import json
import random
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

NICKNAMES = {
    "Robert": ["Bob", "Rob"], "William": ["Bill", "Will"], "Elizabeth": ["Liz", "Beth"],
    "Katherine": ["Kate", "Kathy"], "Michael": ["Mike"], "Jennifer": ["Jen"],
    "Thomas": ["Tom"], "Margaret": ["Maggie", "Peggy"], "Daniel": ["Dan"],
    "Christopher": ["Chris"], "Alexander": ["Alex"], "Nicholas": ["Nick"],
    "Jonathan": ["Jon"], "Samantha": ["Sam"], "Benjamin": ["Ben"],
}
PLAIN_FIRST = ["Chloé", "Zoë", "José", "Priya", "Omar", "Fatima", "Mei", "Hiroshi",
               "Ana", "Dev", "Léa", "Mateo", "Aisha", "Noah", "Olivia", "Ivan", "Sofia", "Raj"]
LAST = ["Smith", "Tremblay", "Patel", "García", "Roy", "Kim", "Lee", "Martin", "Gagnon",
        "Wong", "Singh", "Côté", "Haddad", "Okafor", "Müller", "Rossi", "Silva", "Cohen",
        "Bouchard", "Johnson", "Brown", "Lefebvre", "Chen", "Ahmed"]
VIET = [("Nguyễn", "Thị Hà"), ("Trần", "Văn An"), ("Lê", "Minh Tuấn"), ("Phạm", "Thu Trang"),
        ("Đặng", "Quốc Bảo"), ("Võ", "Ngọc Lan")]
CITIES = ["Montréal", "Toronto", "Québec", "Vancouver", "Ottawa", "Calgary", "Halifax"]
DOMAINS = ["example.com", "mail.com", "gmail.com", "example.ca"]
def strip_accents(s):
    """What a system without Unicode support stores: base letters only (Đ becomes D)."""
    decomposed = unicodedata.normalize("NFKD", s.replace("Đ", "D").replace("đ", "d"))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def ascii_slug(s):
    return "".join(ch for ch in strip_accents(s).lower() if ch.isalpha())


def typo(rng, s):
    if len(s) < 4:
        return s
    i = rng.randrange(1, len(s) - 1)
    kind = rng.choice(["swap", "drop", "double", "sub"])
    if kind == "swap":
        return s[:i] + s[i + 1] + s[i] + s[i + 2:]
    if kind == "drop":
        return s[:i] + s[i + 1:]
    if kind == "double":
        return s[:i] + s[i] + s[i:]
    return s[:i] + rng.choice("aeiourstnl") + s[i + 1:]


def phone_digits(rng):
    return f"{rng.choice(['416', '514', '604', '613', '403', '902'])}555{rng.randrange(0, 10000):04d}"


def format_phone(rng, digits):
    a, b, c = digits[:3], digits[3:6], digits[6:]
    return rng.choice([f"{a}-{b}-{c}", f"({a}) {b}-{c}", f"+1 {a} {b} {c}", f"{a}{b}{c}", f"{a}.{b}.{c}"])


def make_people(rng):
    people = []
    firsts = list(NICKNAMES) + PLAIN_FIRST
    used = set()
    while len(people) < 54:
        if rng.random() < 0.12:
            last, first = rng.choice(VIET)
            viet = True
        else:
            first, last = rng.choice(firsts), rng.choice(LAST)
            viet = False
        if (first, last) in used:
            continue
        used.add((first, last))
        people.append({"first": first, "last": last, "viet": viet})
    # Hard negatives 1: different people with the same full name.
    for first, last in [("Robert", "Smith"), ("Mei", "Chen"), ("José", "García")]:
        if (first, last) not in used:
            people.append({"first": first, "last": last, "viet": False})
            used.add((first, last))
        people.append({"first": first, "last": last, "viet": False})
    for i, p in enumerate(people):
        p["entity_id"] = f"E{i + 1:03d}"
        p["city"] = rng.choice(CITIES)
        p["phone"] = phone_digits(rng)
        local = f"{ascii_slug(p['first'])}.{ascii_slug(p['last'])}"
        if any(q.get("email_local") == local for q in people[:i]):
            local += str(rng.randrange(2, 99))
        p["email_local"] = local
        p["domain"] = rng.choice(DOMAINS)
    # Hard negatives 2: family members share a surname, a phone and a city.
    n = len(people)
    for k, (first, partner) in enumerate([("Andy", 0), ("Linh", 1)]):
        base = people[partner * 7 + 3]
        people.append({"first": first if not base["viet"] else "Văn Minh", "last": base["last"],
                       "viet": base["viet"], "entity_id": f"E{n + k + 1:03d}", "city": base["city"],
                       "phone": base["phone"], "email_local": f"{first.lower()}.{ascii_slug(base['last'])}",
                       "domain": rng.choice(DOMAINS)})
    return people


def noisy_name(rng, p):
    first, last = p["first"], p["last"]
    if first in NICKNAMES and rng.random() < 0.35:
        first = rng.choice(NICKNAMES[first])
    if rng.random() < 0.2:
        if rng.random() < 0.5:
            first = typo(rng, first)
        else:
            last = typo(rng, last)
    if rng.random() < 0.4:
        first, last = strip_accents(first), strip_accents(last)
    return first, last


def styled(rng, s):
    r = rng.random()
    if r < 0.12:
        return s.upper()
    if r < 0.2:
        return s.lower()
    if r < 0.28:
        return "  " + s.replace(" ", "  ") + " "
    return s


def noisy_email(rng, p):
    if rng.random() < 0.12:
        return ""
    local, domain = p["email_local"], p["domain"]
    if domain == "gmail.com" and rng.random() < 0.5:
        local = rng.choice([local.replace(".", ""), local + "+shop", local.replace(".", "") + "+promo"])
    email = f"{local}@{domain}"
    if rng.random() < 0.25:
        email = email.upper() if rng.random() < 0.4 else email.capitalize()
    if rng.random() < 0.1:
        email = " " + email + " "
    return email


def noisy_city(rng, p, moved):
    city = moved or p["city"]
    r = rng.random()
    if r < 0.3:
        city = strip_accents(city)
    if r > 0.85:
        city = city.upper()
    return city


def generate(out: Path) -> None:
    rng = random.Random(3636)
    folder = out / "entities"
    folder.mkdir(parents=True, exist_ok=True)
    people = make_people(rng)
    crm, shop, support, truth = [], [], [], []
    start = date(2024, 1, 1)

    for p in people:
        moved = rng.choice([c for c in CITIES if c != p["city"]]) if rng.random() < 0.12 else None
        copies = []
        if rng.random() < 0.85:
            copies.append("crm")
            if rng.random() < 0.1:
                copies.append("crm")                       # entered twice
        if rng.random() < 0.7:
            copies.append("shop")
        if rng.random() < 0.5:
            copies.append("support")
        if not copies:
            copies.append(rng.choice(["crm", "shop", "support"]))
        for n_copy, system in enumerate(copies):
            first, last = noisy_name(rng, p)
            day = start + timedelta(days=rng.randrange(0, 900))
            # the record written after a move carries the new city
            city = noisy_city(rng, p, moved if (moved and n_copy == len(copies) - 1) else None)
            if moved and n_copy == len(copies) - 1:
                day = date(2026, 6, 1) + timedelta(days=rng.randrange(0, 90))
            email = noisy_email(rng, p)
            phone = "" if rng.random() < 0.12 else format_phone(rng, p["phone"])
            if system == "crm":
                rid = f"CRM-{len(crm) + 1:04d}"
                crm.append([rid, styled(rng, first), styled(rng, last), email, phone, city, day.isoformat()])
            elif system == "shop":
                rid = str(10001 + len(shop))
                if p["viet"]:
                    name = f"{last} {first}" if rng.random() < 0.5 else f"{first} {last}"
                elif rng.random() < 0.3:
                    name = f"{last}, {first}"
                else:
                    name = f"{first} {last}"
                shop.append([rid, styled(rng, name), email, phone, city, day.isoformat()])
            else:
                rid = f"S-{len(support) + 1:03d}"
                name = f"{last} {first}" if p["viet"] and rng.random() < 0.6 else f"{first} {last}"
                seen = datetime(day.year, day.month, day.day, rng.randrange(8, 18), rng.randrange(0, 60))
                support.append({"contact_id": rid, "name": styled(rng, name),
                                "email": email or None, "phone": phone or None, "seen": seen.isoformat()})
            truth.append([system, rid, p["entity_id"]])

    order = list(range(len(shop)))
    rng.shuffle(order)
    with open(folder / "crm.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["crm_id", "first_name", "last_name", "email", "phone", "city", "updated_at"])
        w.writerows(crm)
    with open(folder / "shop.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["customer_no", "name", "email", "phone", "city", "last_order"])
        w.writerows(shop[i] for i in order)
    with open(folder / "support.jsonl", "w", encoding="utf-8") as f:
        for row in support:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(folder / "truth.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "record_id", "entity_id"])
        w.writerows(truth)
