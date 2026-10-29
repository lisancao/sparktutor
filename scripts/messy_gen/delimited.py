"""Sample data for "CSV and Delimited Files".

Writes out/delimited/:
- products.csv: RFC 4180 style CSV (quotes doubled inside quoted fields),
  descriptions with commas and line breaks, SKUs with leading zeros, and
  "NA" as the null marker.
- orders_eu.csv: a European export: UTF-8 byte order mark, "#" comment
  lines, ";" separator, decimal commas with "." thousands separators,
  dd.MM.yyyy dates, and two bad rows (31 September, a non-numeric amount).
- legacy_latin1.tsv: tab separated, ISO-8859-1 encoded, Windows line
  endings, a duplicated and a blank header name.
- stores_fixed.txt: a fixed-width file with a header record, a trailer
  record and one truncated line.
- sales/: three days of the same feed whose columns were reordered on day
  2 and gained a currency column on day 3, with one short row and one
  unparseable amount.
"""
import random
from pathlib import Path


def _q(value: str) -> str:
    """Quote a CSV field the RFC 4180 way when it needs it."""
    if any(ch in value for ch in ',"\n') or value == "":
        return '"' + value.replace('"', '""') + '"'
    return value


def generate(out: Path) -> None:
    rng = random.Random(707)
    folder = out / "delimited"
    (folder / "sales").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ products.csv
    planted = [
        ("00042", "Kettle, steel", "Boils 1.7 L.\nAuto shut-off.", "39.99", "yes", "2026-10-01 09:30:00"),
        ("00107", "Tea mug", 'The "classic" mug', "12.50", "no", "2026-10-01 10:00:00"),
        ("00230", "Spoon set", None, "4.00", "yes", "2026-10-02 08:15:00"),   # empty, unquoted
        ("00231", "Gift card", "", "25.00", "NA", "2026-10-02 08:20:00"),    # empty, quoted
        ("10007", "Teapot", "NA", "NA", "yes", "2026-10-03 12:00:00"),
    ]
    nouns = ["Bowl", "Plate", "Whisk", "Ladle", "Tray", "Jar", "Grater", "Sieve"]
    adjectives = ["blue", "large", "bamboo", "enamel", "glass"]
    filler = []
    for i in range(10):
        sku = f"{rng.randint(1, 99999):05d}"
        name = f"{rng.choice(nouns)}, {rng.choice(adjectives)}" if i % 3 == 0 else rng.choice(nouns)
        desc = rng.choice(["Dishwasher safe.", "Hand wash only.\nDo not microwave.",
                           'Sold as a "set of 2".', "Made in Portugal, 2026."])
        price = f"{rng.randint(100, 9999) / 100:.2f}"
        stock = rng.choice(["yes", "no"])
        updated = f"2026-10-0{rng.randint(1, 4)} {rng.randint(8, 18):02d}:{rng.randint(0, 59):02d}:00"
        filler.append((sku, name, desc, price, stock, updated))
    lines = ["sku,name,description,price,in_stock,updated_at"]
    for row in planted + filler:
        lines.append(",".join("" if v is None else _q(v) for v in row))
    (folder / "products.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ------------------------------------------------------------ orders_eu.csv
    customers = ["Müller GmbH", "Café Lumière", "Nguyễn & Co", "Zoë B.", "Øresund AB", "O'Brien Ltd",
                 "Šimek s.r.o.", "Ana Peña"]
    eu = ["# Export Kassensystem 2026-10-05", "# Beträge in EUR",
          "order_id;sku;customer;amount;order_date;note",
          '1001;00042;Müller GmbH;1.234,50;01.10.2026;"Lieferung; Tor 3"',
          "1002;00107;Café Lumière;12,50;02.10.2026;",
          "1003;00230;Nguyễn & Co;7,00;31.09.2026;",
          "1004;00231;Zoë B.;25;03.10.2026;Geschenk",
          "1005;00042;Øresund AB;2.000,00;04.10.2026;",
          "1006;10007;O'Brien Ltd;abc;05.10.2026;"]
    for n in range(1007, 1019):
        euros = rng.randint(100, 350000)
        whole, cents = divmod(euros, 100)
        amount = f"{whole:,}".replace(",", ".") + f",{cents:02d}"
        eu.append(f"{n};{rng.choice(['00042', '00107', '00230', '10007'])};{rng.choice(customers)};"
                  f"{amount};{rng.randint(1, 5):02d}.10.2026;")
    (folder / "orders_eu.csv").write_bytes(b"\xef\xbb\xbf" + ("\n".join(eu) + "\n").encode("utf-8"))

    # ------------------------------------------------------------ legacy_latin1.tsv
    legacy = [["id", "name", "city", "name", "", "notes"],
              ["1", "Zoë", "Montréal", "ZOË", "", "café crème"],
              ["2", "José", "São Paulo", "JOSÉ", "", "señor"],
              ["3", "Françoise", "Besançon", "FRANÇOISE", "x", "déjà vu"],
              ["4", "Ana", "Toronto", "ANA", "", ""]]
    text = "".join("\t".join(r) + "\r\n" for r in legacy)
    (folder / "legacy_latin1.tsv").write_bytes(text.encode("iso-8859-1"))

    # ------------------------------------------------------------ stores_fixed.txt
    # columns: id 1-4, name 5-24, city 25-36, opened 37-44 (yyyyMMdd), sales cents 45-54
    stores = [("0001", "Corner Store", "Toronto", "20190301", 1250050),
              ("0002", "Le Petit Marché", "Montréal", "20200615", 999),
              ("0003", "Pho Kitchen", "Hà Nội", "20211101", 7342210),
              ("0004", "Harbour Books", "Halifax", "20230120", 0)]
    fixed = ["HDR20261005STORES"]
    for sid, name, city, opened, cents in stores:
        fixed.append(f"{sid}{name:<20}{city:<12}{opened}{cents:010d}")
    fixed.append("0005Broken Line")
    fixed.append(f"TRL{len(stores):06d}")
    (folder / "stores_fixed.txt").write_text("\n".join(fixed) + "\n", encoding="utf-8")

    # ------------------------------------------------------------ sales/
    day1 = ["id,amount,day", "1,10.50,2026-10-01", "2,11.00,2026-10-01", "3,4.00",
            "4,8.25,2026-10-01", "5,3.10,2026-10-01"]
    day2 = ["day,id,amount", "2026-10-02,6,12.00", "2026-10-02,7,n/a", "2026-10-02,8,9.99",
            "2026-10-02,9,1.01"]
    day3 = ["id,amount,day,currency", "10,13.00,2026-10-03,EUR", "11,2.50,2026-10-03,CAD",
            "12,6.75,2026-10-03,CAD", "13,20.00,2026-10-03,USD"]
    for name, rows in [("sales_2026-10-01.csv", day1), ("sales_2026-10-02.csv", day2),
                       ("sales_2026-10-03.csv", day3)]:
        (folder / "sales" / name).write_text("\n".join(rows) + "\n", encoding="utf-8")
