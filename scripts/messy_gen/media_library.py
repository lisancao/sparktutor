"""Sample data for "Feature Vectors and Similarity Search".

Writes out/media_library/: a small media library where files come in
families (the same product photo or the same sound, recorded or exported
differently), so that "find the most similar file" has a right answer.

images/: synthetic product photos as PNG. Eight families (a red mug, a
blue shirt, a green plant, a yellow banana, a gray laptop, a sunset, a
checkerboard, a sky). Each family has five variants: the original, a
brighter copy, a noisy copy, a copy rendered at a different size and a
copy with the object moved. The mess a real library has is planted too:
one family exported as RGBA, the checkerboard also saved as a gray
image, an exact byte-for-byte duplicate under another name, and a file
that is not a PNG at all.

audio/: short mono 16-bit WAV clips. Eight families (pure tones at 220,
440 and 1000 Hz, a two-note chord, white noise, a rising chirp, a pulsed
beep and a low hum with a harmonic). Each family has five variants: the
original at 4000 samples per second, a quiet copy, a copy with added
noise, a copy detuned by 2 percent and a copy exported at 8000 samples
per second (so the sample rate differs inside the library).

labels.csv: file, kind, family for every valid file: the answer key for
checking nearest neighbours. The duplicate is labelled with its family;
the broken file is not listed.
"""
import csv
import math
import random
import struct
import wave
import zlib
from pathlib import Path


# ---------------------------------------------------------------- PNG writer (zlib + struct)
def _png(width, height, channels, pixels):
    """pixels: list of rows, each a list of tuples with `channels` ints 0..255."""
    color_type = {1: 0, 3: 2, 4: 6}[channels]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + bytes(v for px in row for v in px) for row in pixels)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _clamp(v):
    return max(0, min(255, int(round(v))))


# Each scene is a function (x, y) in 0..1 coordinates -> (r, g, b), with an
# offset (dx, dy) that moves the object for the "moved" variant.
def _scene(family, dx=0.0, dy=0.0):
    def inside_circle(x, y, cx, cy, r):
        return (x - cx - dx) ** 2 + (y - cy - dy) ** 2 <= r * r

    def inside_rect(x, y, x0, y0, x1, y1):
        return x0 + dx <= x <= x1 + dx and y0 + dy <= y <= y1 + dy

    if family == "mug_red":
        return lambda x, y: (200, 30, 30) if inside_circle(x, y, 0.5, 0.5, 0.3) else (245, 245, 245)
    if family == "shirt_blue":
        return lambda x, y: (30, 60, 190) if inside_rect(x, y, 0.2, 0.15, 0.8, 0.85) else (210, 210, 215)
    if family == "plant_green":
        def plant(x, y):
            if inside_rect(x, y, 0.35, 0.7, 0.65, 0.95):
                return (120, 70, 30)             # the pot
            if inside_circle(x, y, 0.5, 0.4, 0.3):
                return (40, 150, 50)             # the leaves
            return (250, 250, 240)
        return plant
    if family == "banana_yellow":
        return lambda x, y: ((230, 200, 40) if ((x - 0.5 - dx) / 0.4) ** 2 + ((y - 0.5 - dy) / 0.2) ** 2 <= 1
                             else (255, 255, 255))
    if family == "laptop_gray":
        def laptop(x, y):
            if inside_rect(x, y, 0.2, 0.25, 0.8, 0.65):
                return (170, 200, 230)           # the screen
            if inside_rect(x, y, 0.15, 0.2, 0.85, 0.75):
                return (60, 60, 65)              # the body
            return (235, 235, 235)
        return laptop
    if family == "sunset":
        return lambda x, y: (_clamp(250 - 100 * (y - dy)), _clamp(120 - 80 * (y - dy)), _clamp(40 + 120 * (y - dy)))
    if family == "checker":
        return lambda x, y: (20, 20, 20) if (math.floor((x - dx) * 4) + math.floor((y - dy) * 4)) % 2 == 0 else (235, 235, 235)
    if family == "sky":
        def sky(x, y):
            if inside_circle(x, y, 0.3, 0.3, 0.12) or inside_circle(x, y, 0.65, 0.55, 0.15):
                return (250, 250, 250)           # clouds
            return (90 + 60 * y, 150 + 50 * y, 235)
        return sky
    raise ValueError(family)


IMAGE_FAMILIES = ["mug_red", "shirt_blue", "plant_green", "banana_yellow",
                  "laptop_gray", "sunset", "checker", "sky"]


def _render(family, size, rng, brighten=0, noise=0.0, dx=0.0, dy=0.0, channels=3):
    scene = _scene(family, dx, dy)
    rows = []
    for j in range(size):
        row = []
        for i in range(size):
            r, g, b = scene((i + 0.5) / size, (j + 0.5) / size)
            px = []
            for v in (r, g, b):
                v += brighten
                if noise:
                    v += rng.gauss(0, noise)
                px.append(_clamp(v))
            if channels == 1:
                px = [_clamp(0.299 * px[0] + 0.587 * px[1] + 0.114 * px[2])]
            elif channels == 4:
                px.append(255)
            row.append(tuple(px))
        rows.append(row)
    return _png(size, size, channels, rows)


# ---------------------------------------------------------------- WAV writer (stdlib wave)
AUDIO_FAMILIES = ["tone_220", "tone_440", "tone_1000", "chord_300_500",
                  "noise", "chirp", "beeps_800", "hum_150"]


def _signal(family, t, detune, rng):
    f = 1.0 + detune
    if family == "tone_220":
        return math.sin(2 * math.pi * 220 * f * t)
    if family == "tone_440":
        return math.sin(2 * math.pi * 440 * f * t)
    if family == "tone_1000":
        return math.sin(2 * math.pi * 1000 * f * t)
    if family == "chord_300_500":
        return 0.5 * math.sin(2 * math.pi * 300 * f * t) + 0.5 * math.sin(2 * math.pi * 500 * f * t)
    if family == "noise":
        return rng.uniform(-1, 1)
    if family == "chirp":
        # instantaneous frequency rises linearly from 200 Hz to 1600 Hz over 0.125 s
        return math.sin(2 * math.pi * f * (200 * t + 0.5 * (1400 / 0.125) * t * t))
    if family == "beeps_800":
        on = int(t * 40) % 2 == 0           # 12.5 ms on, 12.5 ms off
        return math.sin(2 * math.pi * 800 * f * t) if on else 0.0
    if family == "hum_150":
        return 0.7 * math.sin(2 * math.pi * 150 * f * t) + 0.3 * math.sin(2 * math.pi * 450 * f * t)
    raise ValueError(family)


def _wav(path, family, rng, rate=4000, seconds=0.125, amplitude=0.5, noise=0.0, detune=0.0):
    n = int(rate * seconds)
    frames = bytearray()
    for k in range(n):
        v = amplitude * _signal(family, k / rate, detune, rng)
        if noise:
            v += rng.gauss(0, noise)
        frames += struct.pack("<h", max(-32768, min(32767, int(round(v * 32767)))))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def generate(out: Path) -> None:
    rng = random.Random(3535)
    root = out / "media_library"
    img_dir = root / "images"
    aud_dir = root / "audio"
    img_dir.mkdir(parents=True, exist_ok=True)
    aud_dir.mkdir(parents=True, exist_ok=True)
    labels = []

    for family in IMAGE_FAMILIES:
        channels = 4 if family == "sky" else 3         # one family exported with alpha
        variants = {
            "original": dict(size=24),
            "bright": dict(size=24, brighten=20),
            "noisy": dict(size=24, noise=12.0),
            "large": dict(size=40),
            "moved": dict(size=24, dx=0.08, dy=-0.06),
        }
        for variant, kw in variants.items():
            name = f"{family}_{variant}.png"
            (img_dir / name).write_bytes(_render(family, rng=rng, channels=channels, **kw))
            labels.append((name, "image", family))

    gray = "checker_gray.png"
    (img_dir / gray).write_bytes(_render("checker", 24, rng, channels=1))
    labels.append((gray, "image", "checker"))
    dup = "IMG_0042.png"                              # a re-upload of an existing photo
    (img_dir / dup).write_bytes((img_dir / "mug_red_original.png").read_bytes())
    labels.append((dup, "image", "mug_red"))
    (img_dir / "thumbnail_cache.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"not really a png" * 4)

    for family in AUDIO_FAMILIES:
        variants = {
            "original": dict(),
            "quiet": dict(amplitude=0.08),
            "noisy": dict(noise=0.04),
            "detuned": dict(detune=0.02),
            "hires": dict(rate=8000),
        }
        for variant, kw in variants.items():
            name = f"{family}_{variant}.wav"
            _wav(aud_dir / name, family, rng, **kw)
            labels.append((name, "audio", family))

    with open(root / "labels.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["file", "kind", "family"])
        writer.writerows(sorted(labels, key=lambda r: (r[1], r[0])))
