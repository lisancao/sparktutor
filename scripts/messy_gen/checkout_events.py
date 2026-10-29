"""Sample data for "Streaming Internals: Checkpoints, State and Real-Time Mode".

Writes out/checkout_events/: four JSON Lines files ("drops") that a checkout
service uploads one after another. A streaming query reads one drop per
micro-batch and cuts each user's clicks into sessions (a gap of more than 30
minutes ends a session). The drops contain what a real event stream has:

- drop_1: clean events for several users (09:00 to 09:40 event time).
- drop_2: two events re-sent from drop_1 (same event_id: a mobile client
  retried), an event that arrives out of order but inside the watermark, and
  new clicks that extend some sessions.
- drop_3: a user comes back after a long gap (a second session), one event
  re-sent from drop_2, and one event from 08:10 that is far behind the
  watermark, so Spark drops it before the stateful operator sees it.
- drop_4: later events that push the watermark forward, so most sessions
  close; three users stay open at the end.

Timestamps are UTC with a trailing Z. Amounts are only present on "pay".
"""
import json
import random
from pathlib import Path

PAGES = ["/", "/search", "/p/lamp", "/p/desk", "/p/chair", "/cart"]


def generate(out: Path) -> None:
    rng = random.Random(5151)
    d = out / "checkout_events"
    d.mkdir(parents=True, exist_ok=True)
    n = 0

    def ev(user, hh, mm, action=None):
        nonlocal n
        n += 1
        action = action or ("view" if rng.random() < 0.7 else "add")
        e = {"event_id": f"c{n:03d}", "user": user, "action": action,
             "page": "/checkout" if action == "pay" else rng.choice(PAGES),
             "ts": f"2026-10-05T{hh:02d}:{mm:02d}:{rng.randint(0, 59):02d}Z"}
        if action == "pay":
            e["amount"] = round(rng.uniform(10, 90), 2)
        return e

    u1a, u1b, u1c = ev("u1", 9, 0), ev("u1", 9, 4), ev("u1", 9, 9, "pay")
    u2a, u2b, u2c = ev("u2", 9, 2), ev("u2", 9, 15), ev("u2", 9, 21)
    u3a, u3b = ev("u3", 9, 30), ev("u3", 9, 33)
    u4a, u4b = ev("u4", 9, 38), ev("u4", 9, 40)
    drop1 = sorted([u1a, u1b, u1c, u2a, u2b, u2c, u3a, u3b, u4a, u4b], key=lambda e: e["ts"])

    late_ok = ev("u3", 9, 36)                      # out of order, inside the watermark
    u5a = ev("u5", 10, 10)
    drop2 = [u3b, u4a]                             # re-sent by a retrying client
    drop2 += [ev("u2", 9, 48, "pay"), ev("u3", 9, 52), ev("u3", 9, 58, "pay"),
              ev("u4", 10, 5), late_ok, u5a, ev("u5", 10, 12)]

    drop3 = [u5a]                                  # re-sent again
    drop3 += [ev("u1", 10, 45), ev("u1", 10, 50, "pay"),
              ev("u5", 10, 30), ev("u5", 10, 44, "pay"),
              ev("u6", 10, 55), ev("u4", 10, 58)]
    drop3.append({"event_id": "c999", "user": "u2", "action": "view", "page": "/",
                  "ts": "2026-10-05T08:10:00Z"})  # far behind the watermark

    drop4 = [ev("u6", 11, 20), ev("u6", 11, 31, "pay"),
             ev("u1", 11, 40), ev("u7", 11, 48)]

    for i, rows in enumerate([drop1, drop2, drop3, drop4], 1):
        with open(d / f"drop_{i}.jsonl", "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
