"""Sample data for "Final Project: Your Own Connector".

Writes out/casefiles/: a folder per support case in a made-up "case file"
format, the kind of export a ticketing or legal system produces:

    casefiles/
      CASE-0001/
        case.json          the index: metadata plus the list of attachments
        attachments/       mixed files (PDF, PNG, WAV, e-mail, text, JSON)
        changes.log        one line per change: ts | field | old -> new | actor

The index comes in two schema versions, and the folder has planted
problems, each one at a fixed case (see PROBLEMS below): a missing
attachment, a file on disk that the index does not list, a checksum that
does not match, an old (version 1) index, a truncated index, a lowercase
folder with a byte order mark and CRLF line endings, an unknown priority,
malformed and out-of-order change lines, a log without a final newline,
and noise at the top level that is not a case at all.
"""
import hashlib
import json
import math
import random
import struct
import wave
import zlib
from email.message import EmailMessage
from pathlib import Path

# Which case carries which planted problem (the lesson and its harness rely on these)
PROBLEMS = {
    "CASE-0004": "index lists scan.png, which is not on disk",
    "CASE-0005": "stray.tmp is on disk but not in the index",
    "CASE-0006": "receipt.pdf does not match the sha256 in the index",
    "CASE-0007": "version 1 index (id, created as epoch seconds, state, prio, labels)",
    "CASE-0008": "case.json is truncated (invalid JSON)",
    "CASE-0009": "lowercase folder name, UTF-8 BOM, CRLF line endings, +02:00 offset",
    "CASE-0010": "priority 'urgent' is not one of P1 to P4",
}


def png(width, height, rgb):
    """A valid RGB PNG of one colour (stdlib only)."""
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def wav(path, seconds, freq, rate=8000):
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(frames)))


def pdf(lines):
    """A tiny uncompressed one-page-per-line PDF, like the course's pdf/ samples."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(lines)))
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(lines)} >>")
    for i, text in enumerate(lines):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Contents {4 + 2 * i} 0 R >>")
        stream = f"BT /F1 12 Tf 20 50 Td ({text}) Tj ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def email(subject, body, sender="customer@example.com"):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "support@example.com"
    msg["Subject"] = subject
    msg["Date"] = "Mon, 02 Mar 2026 09:00:00 +0000"
    msg.set_content(body)
    return bytes(msg)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def change(ts, field, old, new, actor):
    return f"{ts} | {field} | {old} -> {new} | {actor}"


def generate(out: Path) -> None:
    rng = random.Random(5656)
    root = out / "casefiles"
    root.mkdir(parents=True, exist_ok=True)
    actors = ["ana", "binh", "chloe", "dev", "emma"]

    def write_case(folder, index, files, log_lines, *, bom=False, crlf=False, final_newline=True,
                   raw_index=None):
        d = root / folder
        (d / "attachments").mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            if isinstance(data, Path):      # already written (WAV)
                continue
            (d / "attachments" / name).write_bytes(data)
        text = raw_index if raw_index is not None else json.dumps(index, indent=2, ensure_ascii=False)
        (d / "case.json").write_bytes(("\ufeff" if bom else "").encode("utf-8") + text.encode("utf-8"))
        nl = "\r\n" if crlf else "\n"
        body = nl.join(log_lines) + (nl if final_newline else "")
        (d / "changes.log").write_bytes(("\ufeff" if bom else "").encode("utf-8") + body.encode("utf-8"))

    def listing(files, names=None):
        return [{"name": n, "sha256": sha(files[n]), "bytes": len(files[n])} for n in (names or files)]

    def log_for(opened_day, n, start_status="new"):
        """n well-formed change lines, minutes apart, for a case opened on opened_day."""
        statuses = [start_status, "open", "triage", "waiting", "open", "resolved", "closed"]
        lines = []
        for i in range(n):
            ts = f"{opened_day}T{9 + i // 6:02d}:{(i * 7) % 60:02d}:00Z"
            if i % 3 == 2:
                lines.append(change(ts, "priority", f"P{rng.randint(2, 4)}", f"P{rng.randint(1, 3)}", rng.choice(actors)))
            else:
                k = min(i, len(statuses) - 2)
                lines.append(change(ts, "status", statuses[k], statuses[k + 1], rng.choice(actors)))
        return lines

    # CASE-0001: an ordinary case, e-mail plus invoice
    f1 = {"request.eml": email("Refund for order 1001", "Hello,\nI was charged twice for order 1001.\nThanks"),
          "invoice_1001.pdf": pdf(["Invoice 1001 total 42.50 CAD", "Thank you for shopping"])}
    write_case("CASE-0001", {
        "schema": 2, "case_id": "CASE-0001", "opened": "2026-03-02T09:15:00Z", "status": "open",
        "priority": "P2", "tags": ["billing", "refund"],
        "meta": {"customer": {"id": "C017", "tier": "gold"}, "channel": "email", "sla_hours": 24},
        "attachments": listing(f1)}, f1,
        ["# exported by helpdesk 7.2"] + log_for("2026-03-02", 6) + [""])

    # CASE-0002: a phone case with the largest attachment (a 2.5 s recording)
    d2 = root / "CASE-0002" / "attachments"
    d2.mkdir(parents=True, exist_ok=True)
    wav(d2 / "call.wav", 2.5, 330)
    f2 = {"call.wav": (d2 / "call.wav").read_bytes(), "screenshot.png": png(24, 12, (40, 90, 200))}
    write_case("CASE-0002", {
        "schema": 2, "case_id": "CASE-0002", "opened": "2026-03-03T14:02:00Z", "status": "closed",
        "priority": "P3", "tags": ["phone", "audio"],
        "meta": {"channel": "phone", "recording": {"seconds": 2.5, "rate": 8000}},
        "attachments": listing(f2)}, {"screenshot.png": f2["screenshot.png"]},
        log_for("2026-03-03", 7))

    # CASE-0003: Latin-1 notes and a JSON export; the log has no final newline
    f3 = {"notes.txt": "Client très mécontent, rappeler lundi.\n".encode("latin-1"),
          "export.json": json.dumps({"order": 1003, "items": [{"sku": "A-1", "qty": 2}]}).encode()}
    write_case("CASE-0003", {
        "schema": 2, "case_id": "CASE-0003", "opened": "2026-03-05T08:30:00Z", "status": "triage",
        "priority": "P1", "tags": ["escalation"],
        "meta": {"customer": {"id": "C003"}, "escalated": True},
        "attachments": listing(f3)}, f3,
        log_for("2026-03-05", 4), final_newline=False)

    # CASE-0004: the index lists scan.png, which is missing
    f4 = {"photo.png": png(16, 16, (200, 30, 30)), "scan.png": png(8, 8, (0, 0, 0))}
    write_case("CASE-0004", {
        "schema": 2, "case_id": "CASE-0004", "opened": "2026-03-09T10:00:00Z", "status": "waiting",
        "priority": "P2", "tags": ["damaged"],
        "meta": {"customer": {"id": "C021", "tier": "silver"}, "order": 1044},
        "attachments": listing(f4)}, {"photo.png": f4["photo.png"]},
        log_for("2026-03-09", 5) + ["status changed by ana"])           # malformed line

    # CASE-0005: stray.tmp is on disk but not in the index
    f5 = {"label.png": png(12, 6, (10, 160, 60))}
    write_case("CASE-0005", {
        "schema": 2, "case_id": "CASE-0005", "opened": "2026-03-11T16:45:00Z", "status": "open",
        "priority": "P4", "tags": [],
        "meta": {"channel": "web", "browser": "Firefox 141"},
        "attachments": listing(f5)}, {**f5, "stray.tmp": b"~lock~" * 10},
        log_for("2026-03-11", 3))

    # CASE-0006: receipt.pdf on disk differs from the file the index was made from
    good = pdf(["Receipt 6006 paid 12.00 CAD"])
    write_case("CASE-0006", {
        "schema": 2, "case_id": "CASE-0006", "opened": "2026-03-12T11:20:00Z", "status": "resolved",
        "priority": "P3", "tags": ["billing"],
        "meta": {"customer": {"id": "C044", "tier": "gold"}, "refund": {"amount": "12.00", "currency": "CAD"}},
        "attachments": [{"name": "receipt.pdf", "sha256": sha(good), "bytes": len(good)}]},
        {"receipt.pdf": pdf(["Receipt 6006 paid 21.00 CAD"])},
        # an out-of-order line: its timestamp is earlier than the one before it
        log_for("2026-03-12", 3) + [change("2026-03-12T08:00:00Z", "status", "open", "resolved", "emma")])

    # CASE-0007: a version 1 index
    f7 = {"photo.png": png(10, 10, (250, 200, 0))}
    v1 = {"id": "case-0007", "created": 1772616600, "state": "OPEN", "prio": 2,
          "labels": "billing, vip", "attachments": ["photo.png"],
          "extra": {"imported_from": "legacy-crm", "legacy_id": 7731}}
    write_case("CASE-0007", v1, f7, log_for("2026-03-04", 3))

    # CASE-0008: a truncated index
    f8 = {"note.txt": b"Call back after the holidays.\n"}
    full = json.dumps({"schema": 2, "case_id": "CASE-0008", "opened": "2026-03-20T09:00:00Z",
                       "status": "open", "priority": "P2", "tags": ["callback"],
                       "attachments": listing(f8)}, indent=2)
    write_case("CASE-0008", None, f8, log_for("2026-03-20", 2), raw_index=full[: len(full) // 2])

    # case-0009: lowercase folder, BOM, CRLF, a +02:00 offset, non-ASCII metadata
    f9 = {"lettre.eml": email("Réclamation colis abîmé", "Bonjour,\nLe colis est arrivé abîmé.\nMerci",
                              sender="client@exemple.fr")}
    write_case("case-0009", {
        "schema": 2, "case_id": "CASE-0009", "opened": "2026-03-21T10:30:00+02:00", "status": "open",
        "priority": "P2", "tags": ["damaged", "fr"],
        "meta": {"customer": {"id": "C090", "name": "Hélène Côté"}, "channel": "email", "lang": "fr"},
        "attachments": listing(f9)}, f9,
        log_for("2026-03-21", 4), bom=True, crlf=True)

    # CASE-0010: an unknown priority value, and a blank and a malformed line in the log
    f10 = {"photo.png": png(20, 10, (90, 90, 90))}
    lines10 = log_for("2026-03-25", 4)
    lines10[2:2] = ["", "2026-03-25T09:30:00Z | status | open triage | dev"]   # no arrow
    write_case("CASE-0010", {
        "schema": 2, "case_id": "CASE-0010", "opened": "2026-03-25T09:00:00Z", "status": "open",
        "priority": "urgent", "tags": ["vip"],
        "meta": {"customer": {"id": "C017", "tier": "gold"}, "sla_hours": 4},
        "attachments": listing(f10)}, f10, lines10)

    # Noise at the top level: none of these is a case
    (root / "README.txt").write_text("Exported cases. One folder per case.\n")
    (root / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1" + b"\x00" * 24)
    (root / "_staging" / "job-3f2a" / "CASE-0099").mkdir(parents=True, exist_ok=True)
    (root / "_staging" / "job-3f2a" / "CASE-0099" / "case.json").write_text(
        '{"schema": 2, "case_id": "CASE-0099", "status": "open"}\n')
