"""Sample data for "Streaming Messy Data: Drift, Dead Letters and State".

Writes out/clickstream/: four JSON Lines files ("drops") that a web shop's
tracker uploads one after another. Read in order, they contain the problems a
real event stream has:

- drop_01: clean events (09:00 to 09:12, event time).
- drop_02: two events re-sent from drop_01, one event sent twice, a
  truncated line, a timestamp that is not a timestamp, an event with no user,
  and an event from a device whose clock is a day ahead.
- drop_03: the tracker was upgraded. `type` is now `event_type`, and a new
  `app_version` field appears. Two events arrive out of order, a little late.
- drop_04: one event re-sent from drop_03, two events so late (09:05) that a
  10 minute watermark has already passed them, and newer events.

Each user's events form sessions separated by gaps of more than 5 minutes.
"""
import json
import random
from pathlib import Path


def _event(eid, user, kind, page, ts, v2=False, version="2.0"):
    e = {"event_id": eid, "user_id": user}
    if v2:
        e["event_type"] = kind
    else:
        e["type"] = kind
    e["page"] = page
    e["ts"] = f"2026-10-05T{ts}"
    if v2:
        e["app_version"] = version
    return e


def generate(out: Path) -> None:
    rng = random.Random(3333)
    d = out / "clickstream"
    d.mkdir(parents=True, exist_ok=True)
    pages = ["/", "/search", "/p/lamp", "/p/desk", "/p/chair", "/cart"]
    n = 0

    def nid():
        nonlocal n
        n += 1
        return f"e{n:03d}"

    def browse(user, minutes, v2=False):
        rows = []
        for m in minutes:
            kind = "page_view" if rng.random() < 0.75 else "add_to_cart"
            rows.append(_event(nid(), user, kind, rng.choice(pages), f"{9 + m // 60:02d}:{m % 60:02d}:{rng.randint(0, 59):02d}", v2))
        return rows

    # drop 1: three users, clean
    drop1 = browse("u1", [0, 1, 3]) + browse("u2", [2, 4, 5, 6]) + browse("u3", [8, 9, 12])
    drop1.sort(key=lambda e: e["ts"])

    # drop 2: u1 comes back after a gap (new session), u2 continues, u4 starts
    drop2 = browse("u1", [14, 15]) + browse("u2", [10, 11]) + browse("u4", [16, 18, 20, 24])
    drop2.append(_event(nid(), "u2", "checkout", "/checkout", "09:11:30"))
    drop2.sort(key=lambda e: e["ts"])
    lines2 = [json.dumps(e) for e in drop2]
    lines2.insert(2, json.dumps(drop1[0]))                  # re-sent from drop 1
    lines2.insert(5, json.dumps(drop1[4]))                  # re-sent from drop 1
    lines2.insert(7, lines2[6])                              # the same line twice
    lines2.insert(9, '{"event_id": "e900", "user_id": "u3", "type": "page_v')  # truncated
    bad_ts = _event("e901", "u3", "page_view", "/", "00:00:00")
    bad_ts["ts"] = "yesterday"
    lines2.insert(11, json.dumps(bad_ts))                    # not a timestamp
    no_user = _event("e902", None, "page_view", "/", "09:21:00")
    del no_user["user_id"]
    lines2.insert(12, json.dumps(no_user))                   # no user
    wrong_clock = _event("e903", "u4", "page_view", "/cart", "09:22:00")
    wrong_clock["ts"] = "2026-10-06T09:22:00"
    lines2.insert(14, json.dumps(wrong_clock))               # a device clock a day ahead

    # drop 3: tracker v2 (event_type, app_version), two slightly late events
    drop3 = browse("u3", [26, 27, 29], v2=True) + browse("u4", [25, 31], v2=True) + browse("u5", [30, 33, 36], v2=True)
    drop3.sort(key=lambda e: e["ts"])
    drop3.insert(3, _event(nid(), "u1", "page_view", "/p/desk", "09:16:40", v2=True))  # late, within watermark
    drop3.insert(6, _event(nid(), "u4", "add_to_cart", "/p/lamp", "09:22:10", v2=True))  # late, within watermark
    lines3 = [json.dumps(e) for e in drop3]

    # drop 4: one re-sent v2 event, two events far too late, newer events
    drop4 = browse("u5", [38, 40], v2=True) + browse("u6", [41, 42, 50], v2=True) + browse("u3", [45], v2=True)
    drop4.append(_event(nid(), "u5", "checkout", "/checkout", "09:41:30", v2=True))
    drop4.sort(key=lambda e: e["ts"])
    lines4 = [json.dumps(e) for e in drop4]
    lines4.insert(1, json.dumps(drop3[0]))                   # re-sent from drop 3
    lines4.insert(3, json.dumps(_event(nid(), "u2", "page_view", "/cart", "09:05:00", v2=True)))   # far too late
    lines4.insert(5, json.dumps(_event(nid(), "u2", "add_to_cart", "/p/chair", "09:05:20", v2=True)))  # far too late

    for name, lines in (("drop_01.jsonl", [json.dumps(e) for e in drop1]), ("drop_02.jsonl", lines2),
                        ("drop_03.jsonl", lines3), ("drop_04.jsonl", lines4)):
        (d / name).write_text("\n".join(lines) + "\n")
