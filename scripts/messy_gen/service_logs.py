"""Sample data for "Python UDTFs in Depth".

Writes out/service_logs/kv.log: one morning of a web service's logs in the
key=value ("logfmt") style, as two hosts wrote them into one file.

- Each line has ts, level and usually user, action, ms, region and msg keys.
- Users u1 to u6 visit in sessions: events a few minutes apart, then a
  pause of 35 to 80 minutes before the next session.
- Health checks have no user.
- The two hosts' clocks and buffers interleave lines, so the file is only
  roughly in time order (lines can be up to 90 seconds out of order).
- Planted problems at fixed places: blank lines, a comment line, a
  duplicated key, an upper-case key, a flag with no value, a value that
  should be a number and is not, quoted values with spaces, escaped quotes
  and non-ASCII text, and a line cut off inside a quoted value.
"""
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACTIONS = ["view", "view", "view", "search", "add_to_cart", "checkout"]
REGIONS = ["ca-east", "us-west", "vn-north"]


def _fmt(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def generate(out: Path) -> None:
    rng = random.Random(3030)
    d = out / "service_logs"
    d.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 10, 7, 9, 0, 0, tzinfo=timezone.utc)

    events = []  # (true time, line)
    for u in range(1, 7):
        user = f"u{u}"
        region = REGIONS[u % 3]
        t = start + timedelta(minutes=rng.randint(0, 20), seconds=rng.randint(0, 59))
        for _ in range(rng.randint(2, 4)):
            for _ in range(rng.randint(3, 7)):
                action = rng.choice(ACTIONS)
                ms = rng.randint(4, 900)
                events.append((t, f"ts={_fmt(t)} level=INFO user={user} action={action} "
                                  f"ms={ms} region={region}"))
                t += timedelta(minutes=rng.randint(1, 6), seconds=rng.randint(0, 59))
            t += timedelta(minutes=rng.randint(35, 80))
    t = start
    while t < start + timedelta(hours=4):
        events.append((t, f"ts={_fmt(t)} level=DEBUG action=healthcheck ms={rng.randint(1, 3)}"))
        t += timedelta(minutes=20)

    # Two hosts: each line is written up to 90 seconds late
    events.sort(key=lambda e: e[0] + timedelta(seconds=rng.randint(0, 90)))
    lines = [line for _, line in events]

    # Planted problems, at fixed positions so the lesson can count them
    def patch(i, old, new):
        """Change the first user line at or after position i."""
        while old not in lines[i] or "user=" not in lines[i]:
            i += 1
        lines[i] = lines[i].replace(old, new, 1)

    patch(5, "level=INFO ", 'level=WARN msg="card \\"declined\\" twice" ')
    patch(9, " region=", ' msg="Thanh toán chậm" region=')
    patch(14, " action=", " action=search action=")        # duplicated key, the last one wins
    patch(21, "level=INFO user=", "level=INFO User=")       # upper-case key
    patch(30, "level=INFO ", "level=INFO retry ")          # a flag without a value
    patch(37, " ms=", " ms=fast ms_was=")                    # not a number
    patch(44, " region=", ' region="" note=')               # an empty quoted value
    lines.insert(12, "")
    lines.insert(40, "# log rotated by logrotate")
    lines.insert(41, "")
    cut = lines[60]
    lines[60] = cut[: cut.index(" ms=")] + ' msg="request timed o'   # cut inside quotes
    (d / "kv.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
