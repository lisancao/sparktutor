"""Sample data for "Binary Records: Avro and Protobuf".

Writes out/binary/: two dumps of Kafka-style topics, one message per line
as JSON ({"topic", "partition", "offset", "key", "value"} with the value
bytes in base64), plus the schemas a schema registry would hold.

orders_topic.jsonl: Avro in the Confluent wire format (a 0 byte, a 4-byte
big-endian schema id, then the Avro binary record). Two schema versions:
  id 1: Order{order_id, user_id, amount, ts}
  id 2: Order{order_id, user_id, total (renamed from amount, with an alias),
              ts, currency (default "CAD"), coupon (nullable), items}
and the problems a real topic has: a tombstone (null value), a message with
a schema id nobody registered, a truncated message, and one message a
misconfigured producer wrote without the Confluent header.

payments_topic.jsonl: Protobuf in the Confluent wire format (0 byte, schema
id, the message-index list, encoded as a single 0 byte for the first
message in the file, then the Protobuf message). Planted: a payment of 0
cents, a payment with the enum's zero value, a message from a newer
producer with a field this schema does not know, and a truncated message.

schemas/: the Avro schemas (.avsc), payments.proto, and payments.desc, the
FileDescriptorSet equivalent to what `protoc --include_imports --descriptor_set_out`
would produce for payments.proto. Everything is encoded by hand with the
standard library, so this file doubles as a reference for both encodings.
"""
import base64
import json
import random
import struct
from pathlib import Path

# ------------------------------------------------------------------ Avro binary encoding


def avro_long(n: int) -> bytes:
    """Avro int and long: zigzag, then a base-128 varint (low 7 bits first)."""
    z = (n << 1) ^ (n >> 63)
    out = bytearray()
    while True:
        b = z & 0x7F
        z >>= 7
        if z:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def avro_string(s: str) -> bytes:
    data = s.encode("utf-8")
    return avro_long(len(data)) + data


def avro_double(x: float) -> bytes:
    return struct.pack("<d", x)


ORDER_V1 = {
    "type": "record", "name": "Order", "namespace": "shop",
    "fields": [
        {"name": "order_id", "type": "string"},
        {"name": "user_id", "type": "long"},
        {"name": "amount", "type": "double"},
        {"name": "ts", "type": {"type": "long", "logicalType": "timestamp-millis"}},
    ],
}
ORDER_V2 = {
    "type": "record", "name": "Order", "namespace": "shop",
    "fields": [
        {"name": "order_id", "type": "string"},
        {"name": "user_id", "type": "long"},
        {"name": "total", "type": "double", "aliases": ["amount"]},
        {"name": "ts", "type": {"type": "long", "logicalType": "timestamp-millis"}},
        {"name": "currency", "type": "string", "default": "CAD"},
        {"name": "coupon", "type": ["null", "string"], "default": None},
        {"name": "items", "default": [], "type": {"type": "array", "items": {
            "type": "record", "name": "Item",
            "fields": [{"name": "sku", "type": "string"}, {"name": "qty", "type": "int"}]}}},
    ],
}


def encode_v1(o) -> bytes:
    return (avro_string(o["order_id"]) + avro_long(o["user_id"]) + avro_double(o["amount"])
            + avro_long(o["ts"]))


def encode_v2(o) -> bytes:
    out = (avro_string(o["order_id"]) + avro_long(o["user_id"]) + avro_double(o["amount"])
           + avro_long(o["ts"]) + avro_string(o["currency"]))
    # A union is the branch index (a long) followed by the value.
    out += avro_long(0) if o["coupon"] is None else avro_long(1) + avro_string(o["coupon"])
    # An array is written in blocks: a count, the items, and a 0 count to end.
    if o["items"]:
        out += avro_long(len(o["items"]))
        for sku, qty in o["items"]:
            out += avro_string(sku) + avro_long(qty)
    out += avro_long(0)
    return out


def confluent(schema_id: int, payload: bytes, message_indexes: bytes = b"") -> bytes:
    return b"\x00" + struct.pack(">I", schema_id) + message_indexes + payload

# ------------------------------------------------------------------ Protobuf binary encoding


def pb_varint(n: int) -> bytes:
    """Protobuf varint (no zigzag: int64 fields store negative numbers in 10 bytes)."""
    n &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def pb_key(field: int, wire_type: int) -> bytes:
    return pb_varint((field << 3) | wire_type)


def pb_int(field: int, value: int) -> bytes:          # wire type 0: varint
    return pb_key(field, 0) + pb_varint(value)


def pb_bytes(field: int, value: bytes) -> bytes:      # wire type 2: length-delimited
    return pb_key(field, 2) + pb_varint(len(value)) + value


def pb_str(field: int, value: str) -> bytes:
    return pb_bytes(field, value.encode("utf-8"))


METHODS = {"METHOD_UNSPECIFIED": 0, "CARD": 1, "CASH": 2, "GIFT_CARD": 3}

PAYMENTS_PROTO = """syntax = "proto3";

package shop;

enum Method {
  METHOD_UNSPECIFIED = 0;
  CARD = 1;
  CASH = 2;
  GIFT_CARD = 3;
}

message Payment {
  string payment_id = 1;
  string order_id = 2;
  int64 amount_cents = 3;
  Method method = 4;
  repeated string flags = 5;
  optional string note = 6;
}
"""


def payments_descriptor_set() -> bytes:
    """payments.proto as a FileDescriptorSet (descriptor.proto field numbers)."""
    def field(name, number, label, ftype, type_name=None, oneof_index=None, proto3_optional=False):
        # FieldDescriptorProto: name=1 number=3 label=4 type=5 type_name=6
        #                       oneof_index=9 json_name=10 proto3_optional=17
        parts = pb_str(1, name) + pb_int(3, number) + pb_int(4, label) + pb_int(5, ftype)
        if type_name:
            parts += pb_str(6, type_name)
        if oneof_index is not None:
            parts += pb_int(9, oneof_index)
        camel = name.split("_")[0] + "".join(w.title() for w in name.split("_")[1:])
        parts += pb_str(10, camel)
        if proto3_optional:
            parts += pb_int(17, 1)
        return parts

    OPTIONAL, REPEATED = 1, 3
    INT64, STRING, ENUM = 3, 9, 14
    # EnumDescriptorProto: name=1 value=2 (EnumValueDescriptorProto: name=1 number=2)
    enum = pb_str(1, "Method") + b"".join(
        pb_bytes(2, pb_str(1, n) + pb_int(2, v)) for n, v in METHODS.items())
    # DescriptorProto: name=1 field=2 oneof_decl=8. A proto3 `optional` field
    # lives in a synthetic oneof named after it.
    message = (pb_str(1, "Payment")
               + pb_bytes(2, field("payment_id", 1, OPTIONAL, STRING))
               + pb_bytes(2, field("order_id", 2, OPTIONAL, STRING))
               + pb_bytes(2, field("amount_cents", 3, OPTIONAL, INT64))
               + pb_bytes(2, field("method", 4, OPTIONAL, ENUM, ".shop.Method"))
               + pb_bytes(2, field("flags", 5, REPEATED, STRING))
               + pb_bytes(2, field("note", 6, OPTIONAL, STRING, oneof_index=0, proto3_optional=True))
               + pb_bytes(8, pb_str(1, "_note")))
    # FileDescriptorProto: name=1 package=2 message_type=4 enum_type=5 syntax=12
    file = (pb_str(1, "payments.proto") + pb_str(2, "shop") + pb_bytes(4, message)
            + pb_bytes(5, enum) + pb_str(12, "proto3"))
    return pb_bytes(1, file)                            # FileDescriptorSet: file=1


def encode_payment(p) -> bytes:
    # proto3 does not write a singular field that holds its default value
    # (0, "", the first enum value): that is why such values read back as NULL.
    out = b""
    if p["payment_id"]:
        out += pb_str(1, p["payment_id"])
    if p["order_id"]:
        out += pb_str(2, p["order_id"])
    if p["amount_cents"]:
        out += pb_int(3, p["amount_cents"])
    if METHODS[p["method"]]:
        out += pb_int(4, METHODS[p["method"]])
    for flag in p["flags"]:
        out += pb_str(5, flag)
    if p["note"] is not None:                           # optional: presence is kept
        out += pb_str(6, p["note"])
    if p.get("tip_cents"):                              # field 7: only newer producers know it
        out += pb_int(7, p["tip_cents"])
    return out


def b64(data):
    return None if data is None else base64.b64encode(data).decode("ascii")


def generate(out: Path) -> None:
    rng = random.Random(1212)
    folder = out / "binary"
    (folder / "schemas").mkdir(parents=True, exist_ok=True)

    base_ms = 1790841600000                             # 2026-10-01T08:00:00Z
    orders, messages = [], []
    for i in range(26):
        order = {
            "order_id": f"O-{2001 + i}",
            "user_id": rng.randint(1, 9),
            "amount": round(rng.uniform(5, 120), 2),
            "ts": base_ms + i * 3_600_000,
            "currency": rng.choice(["CAD", "CAD", "USD"]),
            "coupon": rng.choice([None, None, "FALL10"]),
            "items": [(rng.choice(["P1", "P2", "P3", "P4"]), rng.randint(1, 3))
                      for _ in range(rng.randint(1, 3))],
        }
        version = 1 if i < 12 else 2
        if version == 1:
            value = confluent(1, encode_v1(order))
        else:
            value = confluent(2, encode_v2(order))
        orders.append(order)
        messages.append([order["order_id"], value])

    messages.insert(5, ["O-2003", None])                                   # tombstone
    unknown = dict(orders[20], order_id="O-2900")
    messages.insert(17, ["O-2900", confluent(7, encode_v2(unknown))])       # schema id 7
    messages.insert(23, ["O-2950", confluent(2, encode_v2(dict(orders[22], order_id="O-2950")))[:-9]])
    messages.insert(26, ["O-2960", encode_v1(dict(orders[3], order_id="O-2960"))])   # no header

    with open(folder / "orders_topic.jsonl", "w") as f:
        for offset, (key, value) in enumerate(messages):
            f.write(json.dumps({"topic": "orders", "partition": 0, "offset": offset,
                                "key": key, "value": b64(value)}) + "\n")

    payments = []
    for i, order in enumerate(orders):
        if i in (4, 15):                                # two orders have no payment yet
            continue
        payments.append({
            "payment_id": f"PAY-{9001 + i}",
            "order_id": order["order_id"],
            "amount_cents": int(round(order["amount"] * 100)),
            "method": rng.choice(["CARD", "CARD", "CASH", "GIFT_CARD"]),
            "flags": rng.sample(["fraud_check", "manual", "retry"], rng.randint(0, 2)),
            "note": rng.choice([None, None, "thanks", ""]),
        })
    payments[3]["amount_cents"] = 0                     # fully paid with a coupon
    payments[3]["method"] = "GIFT_CARD"
    payments[6]["method"] = "METHOD_UNSPECIFIED"        # the producer forgot to set it
    payments[9]["tip_cents"] = 250                      # a newer producer
    values = [[p["order_id"], confluent(3, encode_payment(p), b"\x00")] for p in payments]
    values.insert(12, ["O-2013", values[11][1][:-4]])    # truncated
    with open(folder / "payments_topic.jsonl", "w") as f:
        for offset, (key, value) in enumerate(values):
            f.write(json.dumps({"topic": "payments", "partition": 0, "offset": offset,
                                "key": key, "value": b64(value)}) + "\n")

    (folder / "schemas" / "orders-value-1.avsc").write_text(json.dumps(ORDER_V1, indent=2) + "\n")
    (folder / "schemas" / "orders-value-2.avsc").write_text(json.dumps(ORDER_V2, indent=2) + "\n")
    (folder / "schemas" / "payments.proto").write_text(PAYMENTS_PROTO)
    (folder / "schemas" / "payments.desc").write_bytes(payments_descriptor_set())
