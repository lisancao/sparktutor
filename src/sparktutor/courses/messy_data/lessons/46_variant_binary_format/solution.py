"""
The VARIANT Binary Format - Solution

A pure-Python decoder for Spark's VARIANT encoding, an encoder that produces
the same bytes as parse_json, and a reader that rebuilds values from a
shredded Parquet file. Spark itself is the referee for every check.
"""

import datetime
import decimal
import struct
import uuid

from pyspark.sql import SparkSession, functions as sf
from pyspark.sql.types import VariantVal

# Basic types (low 2 bits of a value header byte)
PRIMITIVE, SHORT_STR, OBJECT, ARRAY = 0, 1, 2, 3
EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
EPOCH_NTZ = datetime.datetime(1970, 1, 1)


def _uint(buf, pos, n):
    return int.from_bytes(buf[pos:pos + n], "little")


def _int(buf, pos, n):
    return int.from_bytes(buf[pos:pos + n], "little", signed=True)


# ---- Part 1: decoding ----
def metadata_keys(metadata):
    """The dictionary of a VARIANT metadata blob, as a list of str.

    Byte 0: version in the low 4 bits (must be 1), bit 4 sorted_strings,
    bits 6-7 offset_size - 1. Then the dictionary size and size + 1
    offsets, each offset_size bytes, then the UTF-8 strings.
    """
    header = metadata[0]
    if header & 0x0F != 1:
        raise ValueError(f"unsupported VARIANT metadata version {header & 0x0F}")
    size = ((header >> 6) & 0x03) + 1
    n = _uint(metadata, 1, size)
    offsets = [_uint(metadata, 1 + size * (i + 1), size) for i in range(n + 1)]
    strings = 1 + size * (n + 2)
    return [metadata[strings + offsets[i]:strings + offsets[i + 1]].decode("utf-8")
            for i in range(n)]


def decode(value, metadata, pos=0, keys=None):
    """Decode the VARIANT value starting at `pos` into a Python object.

    None, bool, int, float, decimal.Decimal, str, bytes, datetime.date,
    datetime.datetime (aware UTC for TIMESTAMP, naive for TIMESTAMP_NTZ),
    uuid.UUID, list and dict: the same types VariantVal.toPython() returns.
    """
    if keys is None:
        keys = metadata_keys(metadata)
    header = value[pos]
    basic, info = header & 0x03, header >> 2
    if basic == SHORT_STR:
        return value[pos + 1:pos + 1 + info].decode("utf-8")
    if basic == OBJECT:
        large = (info >> 4) & 1
        id_size = ((info >> 2) & 0x03) + 1
        off_size = (info & 0x03) + 1
        n_size = 4 if large else 1
        n = _uint(value, pos + 1, n_size)
        ids = pos + 1 + n_size
        offs = ids + n * id_size
        data = offs + (n + 1) * off_size
        out = {}
        for i in range(n):
            key = keys[_uint(value, ids + i * id_size, id_size)]
            out[key] = decode(value, metadata, data + _uint(value, offs + i * off_size, off_size), keys)
        return out
    if basic == ARRAY:
        large = (info >> 2) & 1
        off_size = (info & 0x03) + 1
        n_size = 4 if large else 1
        n = _uint(value, pos + 1, n_size)
        offs = pos + 1 + n_size
        data = offs + (n + 1) * off_size
        return [decode(value, metadata, data + _uint(value, offs + i * off_size, off_size), keys)
                for i in range(n)]
    # Primitives: info is the type id
    p = pos + 1
    if info == 0:
        return None
    if info in (1, 2):
        return info == 1
    if info in (3, 4, 5, 6):                       # INT1, INT2, INT4, INT8
        return _int(value, p, {3: 1, 4: 2, 5: 4, 6: 8}[info])
    if info == 7:
        return struct.unpack_from("<d", value, p)[0]
    if info in (8, 9, 10):                         # DECIMAL4, DECIMAL8, DECIMAL16
        scale = value[p]
        unscaled = _int(value, p + 1, {8: 4, 9: 8, 10: 16}[info])
        return decimal.Decimal(unscaled).scaleb(-scale)
    if info == 11:
        return datetime.date(1970, 1, 1) + datetime.timedelta(days=_int(value, p, 4))
    if info == 12:
        return EPOCH + datetime.timedelta(microseconds=_int(value, p, 8))
    if info == 13:
        return EPOCH_NTZ + datetime.timedelta(microseconds=_int(value, p, 8))
    if info == 14:
        return struct.unpack_from("<f", value, p)[0]
    if info == 15:
        return bytes(value[p + 4:p + 4 + _uint(value, p, 4)])
    if info == 16:
        return value[p + 4:p + 4 + _uint(value, p, 4)].decode("utf-8")
    if info == 20:
        return uuid.UUID(bytes=bytes(value[p:p + 16]))
    raise ValueError(f"unknown VARIANT primitive type {info} at byte {pos}")


# ---- Part 2: encoding ----
def _width(n):
    """Bytes needed for an unsigned integer up to n (1 to 4)."""
    return 1 if n <= 0xFF else 2 if n <= 0xFFFF else 3 if n <= 0xFFFFFF else 4


def _le(n, size):
    return n.to_bytes(size, "little", signed=False)


def _decimal(d):
    """DECIMAL4/8/16 bytes for a Decimal, chosen the way Spark does, or None if it does not fit."""
    sign, digits, exp = d.as_tuple()
    scale = max(0, -exp)
    unscaled = int(d.scaleb(scale))
    precision = len(digits) if exp <= 0 else len(digits) + exp
    if scale > 38 or precision > 38:
        return None
    if scale <= 9 and precision <= 9:
        return bytes([8 << 2, scale]) + unscaled.to_bytes(4, "little", signed=True)
    if scale <= 18 and precision <= 18:
        return bytes([9 << 2, scale]) + unscaled.to_bytes(8, "little", signed=True)
    return bytes([10 << 2, scale]) + unscaled.to_bytes(16, "little", signed=True)


def encode(obj):
    """Encode a JSON-like Python object exactly as Spark's parse_json would.

    Supports None, bool, int, float (DOUBLE), decimal.Decimal, str, list and
    dict (str keys, no duplicates). Returns (value, metadata) bytes.
    """
    keys, ids = [], {}

    def key_id(k):
        if k not in ids:
            ids[k] = len(keys)
            keys.append(k.encode("utf-8"))
        return ids[k]

    def enc(o):
        if o is None:
            return b"\x00"
        if o is True:
            return bytes([1 << 2])
        if o is False:
            return bytes([2 << 2])
        if isinstance(o, int):
            for type_id, size in ((3, 1), (4, 2), (5, 4), (6, 8)):
                if -(1 << (8 * size - 1)) <= o < (1 << (8 * size - 1)):
                    return bytes([type_id << 2]) + o.to_bytes(size, "little", signed=True)
            as_decimal = _decimal(decimal.Decimal(o))
            return as_decimal if as_decimal is not None else enc(float(o))
        if isinstance(o, float):
            return bytes([7 << 2]) + struct.pack("<d", o)
        if isinstance(o, decimal.Decimal):
            as_decimal = _decimal(o)
            return as_decimal if as_decimal is not None else enc(float(o))
        if isinstance(o, str):
            b = o.encode("utf-8")
            if len(b) <= 63:
                return bytes([(len(b) << 2) | SHORT_STR]) + b
            return bytes([16 << 2]) + _le(len(b), 4) + b
        if isinstance(o, list):
            parts = [enc(x) for x in o]
            offsets, total = [], 0
            for part in parts:
                offsets.append(total)
                total += len(part)
            off_size = _width(total)
            large = len(parts) > 0xFF
            header = bytes([(((int(large) << 2) | (off_size - 1)) << 2) | ARRAY])
            return (header + _le(len(parts), 4 if large else 1)
                    + b"".join(_le(x, off_size) for x in offsets + [total]) + b"".join(parts))
        if isinstance(o, dict):
            fields, data = [], b""
            for k, v in o.items():               # key ids in first-seen order, data in input order
                fid = key_id(k)
                fields.append((k, fid, len(data)))
                data += enc(v)
            fields.sort(key=lambda f: f[0])      # the id and offset lists are sorted by key
            id_size = _width(max((f[1] for f in fields), default=0))
            off_size = _width(len(data))
            large = len(fields) > 0xFF
            header = bytes([(((int(large) << 4) | ((id_size - 1) << 2) | (off_size - 1)) << 2) | OBJECT])
            return (header + _le(len(fields), 4 if large else 1)
                    + b"".join(_le(f[1], id_size) for f in fields)
                    + b"".join(_le(f[2], off_size) for f in fields) + _le(len(data), off_size) + data)
        raise TypeError(f"cannot encode {type(o).__name__} as VARIANT")

    value = enc(obj)
    strings = b"".join(keys)
    size = _width(max(len(strings), len(keys)))
    offsets, total = [], 0
    for k in keys:
        offsets.append(total)
        total += len(k)
    metadata = (bytes([1 | ((size - 1) << 6)]) + _le(len(keys), size)
                + b"".join(_le(x, size) for x in offsets + [total]) + strings)
    return value, metadata


# ---- Part 3: shredded Parquet ----
MISSING = object()


def from_shredded(row):
    """Rebuild the Python value of one shredded VARIANT row read with pyarrow.

    `row` is a dict {"metadata": bytes, "value": bytes or None,
    "typed_value": ...} (or None for a SQL NULL). A node with a non-null
    typed_value is shredded (a dict for an object, a list for an array, a
    scalar otherwise); its `value`, if present, holds the object fields that
    were not shredded. A node with only `value` holds VARIANT bytes. A
    field whose value and typed_value are both null is missing.
    """
    if row is None:
        return None
    metadata = row["metadata"]
    keys = metadata_keys(metadata)

    def node(n):
        typed, residual = n.get("typed_value"), n.get("value")
        if typed is None:
            return MISSING if residual is None else decode(residual, metadata, 0, keys)
        if isinstance(typed, dict):
            out = {}
            for k, child in typed.items():
                v = node(child)
                if v is not MISSING:
                    out[k] = v
            if residual is not None:
                out.update(decode(residual, metadata, 0, keys))
            return out
        if isinstance(typed, list):
            return [node(el) for el in typed]
        return typed

    result = node(row)
    return None if result is MISSING else result


# ---- Test harness ----
def same(a, b, path="$"):
    """Compare two decoded values, including Python types; return a message or None."""
    if isinstance(a, dict) and isinstance(b, dict):
        if list(a) != list(b) and sorted(a) != sorted(b):
            return f"{path}: keys {sorted(a)} vs {sorted(b)}"
        for k in b:
            msg = same(a.get(k, "<missing>"), b[k], f"{path}.{k}")
            if msg:
                return msg
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} elements vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            msg = same(x, y, f"{path}[{i}]")
            if msg:
                return msg
        return None
    if type(a) is not type(b) or a != b:
        return f"{path}: you have {a!r} ({type(a).__name__}), Spark has {b!r} ({type(b).__name__})"
    return None


def spark_number(text):
    """How parse_json reads a JSON number with a fraction or exponent."""
    if "e" in text or "E" in text:
        return float(text)
    return decimal.Decimal(text)


if __name__ == "__main__":
    import glob
    import json
    import os
    import tempfile

    import pyarrow.parquet as pq

    spark = (SparkSession.builder
        .appName("VariantBinaryFormat")
        .master("local[2]")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    out = tempfile.mkdtemp(prefix="variant_bytes_")
    try:
        # 1. Decode every sample event and compare with Spark (JVM to_json and toPython)
        events = spark.read.option("singleVariantColumn", "v").json("data/messy/events")
        rows = events.select("v", sf.to_json("v").alias("j")).collect()
        checked = 0
        for r in rows:
            if r.v is None:
                continue                          # the truncated line is a NULL variant
            keys = metadata_keys(r.v.metadata)
            assert isinstance(keys, list) and all(isinstance(k, str) for k in keys), (
                f"metadata_keys should return a list of str, got {keys!r}")
            got = decode(r.v.value, r.v.metadata)
            msg = same(got, r.v.toPython())
            assert msg is None, f"Decoding {r.j[:80]}...: {msg}"
            expected = json.loads(r.j, parse_float=decimal.Decimal)
            msg = same(got, expected)
            assert msg is None, f"Your decoded event does not match Spark's to_json: {msg}"
            checked += 1
        assert checked == 60, f"Expected 60 non-null events, decoded {checked}"

        # 2. Every type and every integer width, built by Spark
        wide = "{" + ",".join(f'"key{i:03d}":{i}' for i in range(300)) + "}"
        long_array = "[" + ",".join(str(i) for i in range(300)) + "]"
        cases = spark.sql(f"""SELECT * FROM VALUES
            (parse_json('{{"neg":-129,"big":5000000000,"huge":12345678901234567890,"d4":12.34,
                          "d8":1234567890.12,"d16":0.12345678901234567890,"dbl":1.5e3,
                          "t":true,"f":false,"n":null,"empty":{{}},"none":[],
                          "s":"café","long":"{'x' * 100}"}}')),
            (parse_json('{wide}')),
            (parse_json('{long_array}')),
            (to_variant_object(named_struct(
                'day', date'2026-10-01', 'at', timestamp'2026-10-01 10:00:00',
                'ntz', timestamp_ntz'2026-10-01 10:00:00', 'raw', X'CAFE', 'f', 1.5f,
                'price', 12345.6789bd)))
            AS t(v)""").collect()
        for r in cases:
            msg = same(decode(r.v.value, r.v.metadata), r.v.toPython())
            assert msg is None, f"Edge case {str(r.v)[:60]}...: {msg}"

        # 3. Encode: byte-identical to parse_json, and readable by Spark
        documents = [
            '{"event":"view","user_id":0,"amount":6.13,"ts":"2026-10-01T10:00:00"}',
            '{"b":1,"a":{"z":[1,-200,70000,5000000000],"y":null},"c":true}',
            '{"s":"' + "y" * 80 + '","n":-0.5,"big":9223372036854775808,"e":1E2}',
            wide,
            long_array,
            '[]', '{}', '"x"', 'null',
        ] + [line.strip() for name in sorted(os.listdir("data/messy/events"))
             for line in open(os.path.join("data/messy/events", name)) if line.strip().endswith("}")]
        reference = spark.createDataFrame([(d,) for d in documents], "j string") \
            .select("j", sf.parse_json("j").alias("v")).collect()
        for r in reference:
            obj = json.loads(r.j, parse_float=spark_number)
            enc = encode(obj)
            assert isinstance(enc, tuple) and len(enc) == 2, "encode should return (value, metadata)"
            value, metadata = enc
            assert value == r.v.value, (
                f"Value bytes differ from parse_json for {r.j[:60]}:\n  yours {bytes(value)[:40].hex(' ')}\n"
                f"  Spark {r.v.value[:40].hex(' ')}")
            assert metadata == r.v.metadata, (
                f"Metadata bytes differ for {r.j[:60]}:\n  yours {bytes(metadata)[:40].hex(' ')}\n"
                f"  Spark {r.v.metadata[:40].hex(' ')}")

        # Spark reads your bytes: lookups in a 40-key object use binary search
        forty = {f"k{i:02d}": i for i in reversed(range(40))}
        mine = spark.createDataFrame([(VariantVal(*encode(forty)),)], "v variant")
        got = mine.select(*[sf.variant_get("v", f"$.k{i:02d}", "int").alias(f"k{i:02d}")
                            for i in range(40)]).first().asDict()
        assert got == {k: v for k, v in sorted(forty.items())}, (
            f"Spark could not find every key in your 40-key object: {got}. "
            "Objects of 32 fields or more are searched by binary search, so the "
            "field id list must be sorted by key name")

        # 4. Shredded Parquet: rebuild every event from typed_value and value columns
        path = os.path.join(out, "shredded")
        events.coalesce(1).write.parquet(path)
        cases_path = os.path.join(out, "cases")
        docs = [{"a": i, "b": {"x": i, "y": "s"}} for i in range(40)] + [
            {"a": None, "b": {"x": 1, "y": "s"}}, {"a": 2, "b": {"x": 1, "y": "s", "z": True}},
            {"a": 4}, {"a": 5, "b": {"x": None, "y": "s"}}, {"a": 6, "b": {"y": "s"}, "c": [1]}]
        spark.createDataFrame([(json.dumps(d),) for d in docs], "j string") \
            .select(sf.parse_json("j").alias("v")).coalesce(1).write.parquet(cases_path)
        for p in [path, cases_path]:
            f = glob.glob(os.path.join(p, "*.parquet"))[0]
            cols = [c.path for c in pq.ParquetFile(f).schema]
            assert any(".typed_value." in c for c in cols), f"{f} was not shredded: {cols}"
            shredded = pq.read_table(f).column("v").to_pylist()
            truth = spark.read.parquet(p).collect()
            for i, (srow, trow) in enumerate(zip(shredded, truth)):
                expected = None if trow.v is None else trow.v.toPython()
                msg = same(from_shredded(srow), expected)
                assert msg is None, f"Row {i} of {os.path.basename(p)}: {msg}"

        print(f"Decoded {checked} events and {len(cases)} edge cases like Spark")
        print(f"Encoded {len(reference)} documents byte for byte like parse_json")
        print("Rebuilt every row of two shredded files from typed_value and value")
        print("All tests passed!")
    finally:
        spark.stop()
