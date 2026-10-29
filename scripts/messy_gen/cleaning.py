"""Sample data for "Columns and Expressions: Cleaning Values".

Writes out/cleaning/:
- customers_raw.csv: a customer export where every column is text and
  every kind of value mess is planted (whitespace, case, accents,
  non-breaking spaces, null markers, many date formats, money with
  currency symbols, yes/no booleans, impossible ages, country spellings).
  Rows C001 to C010 are planted by hand; C011 onwards are filler drawn
  with a fixed seed from formats the lesson's cleaning rules accept, so
  every reject in the file comes from the planted rows.
- country_codes.csv: a mapping table from normalized country spellings
  to ISO codes.
"""
import csv
import random
from pathlib import Path

NBSP = "\u00a0"

FIELDS = ["customer_id", "full_name", "email", "phone", "country", "signup_date",
          "lifetime_value", "newsletter", "age", "city"]

# id, full_name, email, phone, country, signup_date, lifetime_value, newsletter, age, city
PLANTED = [
    ("C001", "  ana   maria  nguyen ", " Ana.Nguyen@Example.COM ", "(416) 555-0199", "Canada",
     "2025-03-04", "$1,234.50", "yes", "34", "Montréal"),
    (" c002", "BINH TRAN", "binh@example.com", "416.555.0123", " usa ",
     "2025/03/05", "1234.5", "Y", " 41 ", "MONTREAL"),
    ("C003", f"Zoë{NBSP}Tremblay", "N/A", "+1 416 555 0147", "U.S.",
     "05/03/2025", "$12", "0", "", "montreal  "),
    ("C004", "José\tGarcía", "jose.garcia@example", "555-0100", "Viet Nam",
     "4 Mar 2025", "-$5.00", "N", "-3", "Hà Nội"),
    ("C005", "nguyễn thị hà", "", "", "VN",
     "March 4, 2025", "N/A", "", "29", "Ha Noi"),
    ("C006", "Emma Smith", "emma.at.example.com", "4165550188", "Mars",
     "2025-02-30", "abc", "maybe", "thirty", "Toronto"),
    ("C007", "Dev Patel", "dev@example.ca", "1-416-555-0177", "can",
     "20250306", "1,000", "TRUE", "200", "toronto"),
    ("C008", "MONA LEE", "mona@example.com", "n/a", "France",
     "unknown", " $7.25 ", "false", "52", "Paris"),
    ("C009", "Omar Haddad", "OMAR@EXAMPLE.COM", "416 555 0101", "United States of America",
     "2025-03-09T14:30:00", "$0.99", "no", "61", "  Toronto"),
    ("C010", f"{NBSP} ", "ghost@example.com", "4165550100", "CA",
     "2025-03-10", "$5", "1", "40", "Paris "),
]

FIRST = ["Ana", "Binh", "Chloé", "Dev", "Hoa", "Ivan", "Jade", "Linh", "Quinn", "Rosa", "Tuấn", "Zoë"]
LAST = ["Nguyen", "Tremblay", "Patel", "García", "Tran", "Roy", "Kim", "Lee", "Martin", "Lê"]
COUNTRIES = ["Canada", "CA", "ca", "CAN", "US", "usa", "U.S.", "United States", "VN", "Vietnam", "Viet Nam", "France", "FR"]
CITIES = ["Montréal", "montreal", "MONTRÉAL", "Toronto", "toronto ", "Hà Nội", "Ha Noi", "HA NOI", "Paris", "paris"]
BOOLS = ["yes", "no", "Y", "N", "true", "false", "1", "0", "TRUE", "No"]

COUNTRY_CODES = [
    ("CANADA", "CA"), ("CA", "CA"), ("CAN", "CA"),
    ("US", "US"), ("USA", "US"), ("UNITED STATES", "US"), ("UNITED STATES OF AMERICA", "US"),
    ("VIET NAM", "VN"), ("VIETNAM", "VN"), ("VN", "VN"),
    ("FRANCE", "FR"), ("FR", "FR"),
]


def _filler(rng: random.Random, i: int) -> tuple:
    first, last = rng.choice(FIRST), rng.choice(LAST)
    name = rng.choice([f"{first} {last}", f"{first.upper()} {last.upper()}",
                       f" {first.lower()}  {last.lower()}", f"{first} {last} "])
    email = rng.choice([f"{first.lower()}.{i}@example.com", f" {first.upper()}{i}@Example.org", ""])
    area, mid, end = rng.choice(["416", "514", "604"]), rng.randint(200, 999), rng.randint(1000, 9999)
    phone = rng.choice([f"({area}) {mid}-{end}", f"{area}.{mid}.{end}", f"+1 {area} {mid} {end}",
                        f"{area}{mid}{end}", "n/a"])
    month, day = rng.randint(1, 12), rng.randint(1, 28)
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    long_months = ["January", "February", "March", "April", "May", "June", "July", "August",
                   "September", "October", "November", "December"]
    date = rng.choice([f"2025-{month:02d}-{day:02d}", f"2025/{month:02d}/{day:02d}",
                       f"{day:02d}/{month:02d}/2025", f"{day} {months[month - 1]} 2025",
                       f"{long_months[month - 1]} {day}, 2025", f"2025{month:02d}{day:02d}"])
    cents = rng.randint(0, 500000)
    ltv = rng.choice([f"${cents / 100:,.2f}", f"{cents / 100:.2f}", f" ${cents // 100} ", "N/A"])
    age = rng.choice([str(rng.randint(18, 90)), f" {rng.randint(18, 90)}", ""])
    return (f"C{i:03d}", name, email, phone, rng.choice(COUNTRIES), date, ltv,
            rng.choice(BOOLS), age, rng.choice(CITIES))


def generate(out: Path) -> None:
    rng = random.Random(404)
    folder = out / "cleaning"
    folder.mkdir(parents=True, exist_ok=True)

    rows = list(PLANTED) + [_filler(rng, i) for i in range(11, 41)]
    with open(folder / "customers_raw.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(FIELDS)
        w.writerows(rows)

    with open(folder / "country_codes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["raw", "code"])
        w.writerows(COUNTRY_CODES)
