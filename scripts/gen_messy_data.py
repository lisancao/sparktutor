"""Generate the Messy Data course's sample files with the Python standard library only.

Usage: python scripts/gen_messy_data.py src/sparktutor/data/messy

Everything is deterministic (fixed seed) and synthetic, so it is redistributable.
"""
import json
import math
import random
import struct
import sys
import wave
import zlib
from email.message import EmailMessage
from pathlib import Path

rng = random.Random(42)
out = Path(sys.argv[1])

# ---------------------------------------------------------------- JSON with drift
# v1 (day 1): amount is a number, user is flat.
# v2 (day 2): amount sometimes a string, user nested, new items array of objects.
# v3 (day 3): field renamed (event -> event_type), deeper nesting, a malformed line.
ev = out / "events"
ev.mkdir(parents=True, exist_ok=True)
with open(ev / "events_2026-10-01.json", "w") as f:
    for i in range(20):
        f.write(json.dumps({"event": rng.choice(["view", "purchase"]), "user_id": i % 5,
                            "amount": round(rng.uniform(5, 50), 2), "ts": f"2026-10-01T10:{i:02d}:00"}) + "\n")
with open(ev / "events_2026-10-02.json", "w") as f:
    for i in range(20):
        amt = round(rng.uniform(5, 50), 2)
        f.write(json.dumps({"event": "purchase", "user": {"id": i % 5, "plan": rng.choice(["free", "pro"])},
                            "amount": str(amt) if i % 4 == 0 else amt,
                            "items": [{"sku": f"P{rng.randint(1, 9)}", "qty": rng.randint(1, 3)}
                                      for _ in range(rng.randint(1, 3))],
                            "ts": f"2026-10-02T11:{i:02d}:00"}) + "\n")
with open(ev / "events_2026-10-03.json", "w") as f:
    for i in range(20):
        f.write(json.dumps({"event_type": "purchase", "user": {"id": i % 5, "plan": "pro",
                                                               "geo": {"country": rng.choice(["CA", "VN", "US"])}},
                            "amount": {"value": round(rng.uniform(5, 50), 2), "currency": "CAD"},
                            "items": [{"sku": f"P{rng.randint(1, 9)}", "qty": 1}],
                            "ts": f"2026-10-03T12:{i:02d}:00"}) + "\n")
    f.write('{"event_type": "purchase", "user": {"id": 9\n')  # truncated record

# ---------------------------------------------------------------- XML with drift
xml = out / "xml"
xml.mkdir(exist_ok=True)
with open(xml / "orders.xml", "w") as f:
    f.write("<orders>\n")
    for i in range(10):
        items = "".join(f'<item sku="P{rng.randint(1,9)}"><qty>{rng.randint(1,3)}</qty></item>'
                        for _ in range(rng.randint(1, 3)))
        extra = f"<coupon>SAVE{i}</coupon>" if i % 3 == 0 else ""
        f.write(f'  <order id="{i}" channel="{"web" if i % 2 else "store"}"><customer>C{i%4}</customer>'
                f"<items>{items}</items>{extra}</order>\n")
    f.write("</orders>\n")

# ---------------------------------------------------------------- Logs
logs = out / "logs"
logs.mkdir(exist_ok=True)
paths = ["/", "/cart", "/checkout", "/api/orders", "/api/orders/42", "/login"]
with open(logs / "access.log", "w") as f:
    for i in range(200):
        ip = f"10.0.{rng.randint(0, 3)}.{rng.randint(1, 254)}"
        status = rng.choices([200, 200, 200, 302, 404, 500], k=1)[0]
        f.write(f'{ip} - - [01/Oct/2026:10:{i // 60:02d}:{i % 60:02d} +0000] '
                f'"GET {rng.choice(paths)}?session=s{rng.randint(1,30)} HTTP/1.1" {status} {rng.randint(200, 9000)} '
                f'"-" "Mozilla/5.0"\n')
with open(logs / "app.log", "w") as f:
    for i in range(60):
        lvl = rng.choice(["INFO", "INFO", "WARN", "ERROR"])
        f.write(f"2026-10-01 10:{i:02d}:00,123 {lvl} [worker-{i % 3}] order.Service - processed order={i} ms={rng.randint(5, 900)}\n")
        if lvl == "ERROR":
            f.write("java.lang.IllegalStateException: inventory negative for sku=P3\n"
                    "\tat order.Inventory.reserve(Inventory.java:88)\n"
                    "\tat order.Service.process(Service.java:41)\n")
    # format drift: the team switched to JSON logs half way through the day
    for i in range(20):
        f.write(json.dumps({"ts": f"2026-10-01T11:{i:02d}:00Z", "level": "INFO", "logger": "order.Service",
                            "msg": "processed", "order": 100 + i, "ms": rng.randint(5, 900)}) + "\n")

# ---------------------------------------------------------------- Text documents
docs = out / "docs"
docs.mkdir(exist_ok=True)
topics = {
    "returns": "Customers can return unopened items within 30 days. Refunds go to the original payment method.",
    "shipping": "Standard shipping takes 3 to 5 business days. Express shipping is available in Canada and the US.",
    "warranty": "Electronics carry a one year limited warranty. Batteries are covered for six months.",
    "privacy": "We store order history for seven years. Customers can request deletion of marketing data.",
}
for name, body in topics.items():
    (docs / f"{name}.md").write_text(f"# {name.title()} policy\n\n" + "\n\n".join([body] * 3) + "\n")
(docs / "notes_latin1.txt").write_bytes("Café crème, résumé: déjà vu.\n".encode("latin-1"))

# ---------------------------------------------------------------- Email (stdlib email)
mail = out / "mail"
mail.mkdir(exist_ok=True)
for i in range(4):
    m = EmailMessage()
    m["From"] = f"customer{i}@example.com"
    m["To"] = "support@example.com"
    m["Subject"] = rng.choice(["Where is my order?", "Refund request", "Broken item"])
    m["Date"] = f"Thu, 0{i+1} Oct 2026 09:00:00 +0000"
    m.set_content(f"Hello, order {1000 + i} has a problem. Please help.\n")
    (mail / f"ticket_{i}.eml").write_bytes(bytes(m))


# ---------------------------------------------------------------- PNG images (zlib + struct)
def png(width, height, color_type, pixel):
    """color_type 0 = gray, 2 = RGB, 6 = RGBA; pixel(x, y) -> tuple of channel bytes."""
    raw = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width)) for y in range(height))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


img = out / "images"
(img / "products").mkdir(parents=True, exist_ok=True)
(img / "scans").mkdir(exist_ok=True)
(img / "products" / "red_16x8.png").write_bytes(png(16, 8, 2, lambda x, y: (255, 0, 0)))
(img / "products" / "gradient_32x32.png").write_bytes(png(32, 32, 2, lambda x, y: (x * 8, y * 8, 128)))
(img / "products" / "logo_rgba_12x12.png").write_bytes(png(12, 12, 6, lambda x, y: (0, 0, 255, 255 if x < 6 else 0)))
(img / "scans" / "gray_20x10.png").write_bytes(png(20, 10, 0, lambda x, y: (x * 12,)))
(img / "scans" / "corrupt.png").write_bytes(b"\x89PNG\r\n\x1a\nnot really a png")
(img / "scans" / "readme.txt").write_text("not an image\n")

# ---------------------------------------------------------------- WAV audio (stdlib wave)
aud = out / "audio"
aud.mkdir(exist_ok=True)
for name, freq, amp, secs in [("tone_440", 440, 0.5, 0.25), ("tone_880_quiet", 880, 0.05, 0.25),
                              ("silence", 0, 0.0, 0.5)]:
    rate = 8000
    with wave.open(str(aud / f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * freq * t / rate)))
                          for t in range(int(rate * secs)))
        w.writeframes(frames)


# ---------------------------------------------------------------- Minimal text PDF (hand-written)
def tiny_pdf(pages):
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode()}\nendstream")
        content_id = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    body, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(body))
        body += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(body)
    body += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    body += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    body += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return body


pdf = out / "pdf"
pdf.mkdir(exist_ok=True)
(pdf / "invoice_1001.pdf").write_bytes(tiny_pdf(["Invoice 1001 total 42.50 CAD", "Thank you for shopping"]))
(pdf / "invoice_1002.pdf").write_bytes(tiny_pdf(["Invoice 1002 total 17.00 CAD"]))

total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
for d in sorted(p for p in out.iterdir() if p.is_dir()):
    print(f"{d.name:8} {sum(p.stat().st_size for p in d.rglob('*') if p.is_file()):7d} bytes")
print(f"total    {total:7d} bytes")
