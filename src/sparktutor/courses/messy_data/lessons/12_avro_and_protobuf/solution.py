# spark-connectors: avro, protobuf
"""
Binary Records: Avro and Protobuf - Solution

data/messy/binary/ holds dumps of two Kafka-style topics, one message per
line as JSON with the value bytes in base64:

- orders_topic.jsonl: Avro records in the Confluent wire format
  (0 byte, 4-byte big-endian schema id, Avro binary). Schema ids 1 and 2
  are in schemas/orders-value-<id>.avsc; version 2 renamed amount to total
  (with an alias) and added currency, coupon and items with defaults.
- payments_topic.jsonl: Protobuf messages in the Confluent wire format
  (0 byte, schema id, a message-index byte, Protobuf binary), described by
  schemas/payments.proto and its descriptor set schemas/payments.desc.

Decode both, keep the current version of every order, attach its payment,
and route every message that cannot be decoded to a dead-letter table
with the reason.
"""

from pyspark.sql import SparkSession, Window, functions as F
from pyspark.sql.avro.functions import from_avro
from pyspark.sql.protobuf.functions import from_protobuf

SCHEMAS = "data/messy/binary/schemas"
TOPIC_SCHEMA = "topic STRING, partition INT, offset BIGINT, key STRING, value STRING"


def read_topic(spark, path):
    """The topic dump with `value` decoded from base64 to BINARY (NULL stays NULL)."""
    return (spark.read.schema(TOPIC_SCHEMA).json(path)
            .withColumn("value", F.unbase64("value")))


def split_confluent(df, message_indexes=False):
    """Add the Confluent wire-format pieces to a topic DataFrame.

    framed     true if the first byte is the 0 "magic" byte
    schema_id  bytes 2 to 5 as a big-endian integer
    payload    the bytes after the header. With message_indexes=True
               (Protobuf), the single 0 byte that selects the first message
               type in the schema is skipped too.
    """
    start = 7 if message_indexes else 6
    return df.select(
        "*",
        (F.hex(F.substring("value", 1, 1)) == "00").alias("framed"),
        F.conv(F.hex(F.substring("value", 2, 4)), 16, 10).cast("int").alias("schema_id"),
        F.expr(f"substring(value, {start})").alias("payload"),
    )


def decode_orders(framed, schemas):
    """Decode every framed order into a struct column `o`.

    schemas maps schema id to the writer's Avro schema (JSON text). Each
    message is read with its own writer schema and resolved into the
    newest schema (the highest id), so every row has the same columns.
    PERMISSIVE turns undecodable bytes into a struct of NULLs instead of
    failing the job. An unknown schema id gives a NULL `o`.
    """
    reader = schemas[max(schemas)]
    options = {"avroSchema": reader, "mode": "PERMISSIVE"}
    decoded = None
    for schema_id, writer in sorted(schemas.items()):
        branch = from_avro("payload", writer, options)
        decoded = (F.when(F.col("schema_id") == schema_id, branch) if decoded is None
                   else decoded.when(F.col("schema_id") == schema_id, branch))
    return framed.withColumn("o", decoded)


def classify(decoded, record, known_ids):
    """Add `problem`: why a message cannot be used, or NULL when it decoded.

    record is the name of the decoded struct column. A message is
    "tombstone" (NULL value, a delete), "no confluent header",
    "unknown schema id", or "corrupt" (it did not decode: a NULL struct or,
    from from_avro in PERMISSIVE mode, a struct whose required key is NULL).
    """
    return decoded.withColumn(
        "problem",
        F.when(F.col("value").isNull(), "tombstone")
         .when(~F.col("framed"), "no confluent header")
         .when(~F.col("schema_id").isin(*known_ids), "unknown schema id")
         .when(F.col(f"{record}.order_id").isNull(), "corrupt"))


def current_orders(classified):
    """The current state of every order key, like a compacted topic.

    Usable messages and tombstones are ordered by offset per key; the
    latest one wins, and a key whose latest message is a tombstone is
    deleted. Columns: order_id, user_id, total, currency, coupon, n_items,
    ts, schema_id.
    """
    latest = Window.partitionBy("key").orderBy(F.col("offset").desc())
    return (classified
            .filter(F.col("problem").isNull() | (F.col("problem") == "tombstone"))
            .withColumn("rn", F.row_number().over(latest))
            .filter((F.col("rn") == 1) & F.col("problem").isNull())
            .select("o.order_id", "o.user_id", "o.total", "o.currency", "o.coupon",
                    F.size("o.items").alias("n_items"), "o.ts", "schema_id"))


def decode_payments(framed, desc_path):
    """Decode framed payments into a struct column `p`.

    emit.default.values makes a proto3 field that holds its default (0,
    "", the zero enum value) come back as that value instead of NULL, so a
    payment of 0 cents reads as 0. PERMISSIVE turns bad bytes into NULL.
    """
    options = {"mode": "PERMISSIVE", "emit.default.values": "true"}
    return framed.withColumn("p", from_protobuf("payload", "shop.Payment", desc_path, options))


def order_table(orders, payments):
    """One typed row per current order with its payment, if any.

    Columns: order_id, user_id, total, currency, n_items, ts, paid_cents,
    method (NULL when the producer left it METHOD_UNSPECIFIED), paid.
    """
    pay = payments.filter(F.col("problem").isNull()).select(
        F.col("p.order_id").alias("order_id"),
        F.col("p.amount_cents").alias("paid_cents"),
        F.nullif(F.col("p.method"), F.lit("METHOD_UNSPECIFIED")).alias("method"))
    return (orders.join(pay, "order_id", "left")
            .select("order_id", "user_id", "total", "currency", "n_items", "ts",
                    "paid_cents", "method", F.col("paid_cents").isNotNull().alias("paid"))
            .orderBy("order_id"))


def dead_letters(orders_classified, payments_classified):
    """Every message from both topics that could not be used: topic, offset, key, problem, value.

    Tombstones are deletes, not failures, so they are not dead letters.
    """
    cols = ["topic", "offset", "key", "problem", "value"]
    bad = lambda df: df.filter(F.col("problem").isNotNull() & (F.col("problem") != "tombstone")).select(cols)
    return bad(orders_classified).unionByName(bad(payments_classified)).orderBy("topic", "offset")


# ---- Test harness ----
if __name__ == "__main__":
    import base64
    import json
    import struct

    spark = (SparkSession.builder
             .appName("AvroProtobuf")
             .master("local[*]")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    ORDERS = "data/messy/binary/orders_topic.jsonl"
    PAYMENTS = "data/messy/binary/payments_topic.jsonl"
    DESC = f"{SCHEMAS}/payments.desc"
    schemas = {i: open(f"{SCHEMAS}/orders-value-{i}.avsc").read() for i in (1, 2)}

    # ---- The expected answers, decoded with a few lines of plain Python ----
    class Reader:
        def __init__(self, data):
            self.data, self.pos = data, 0

        def byte(self):
            if self.pos >= len(self.data):
                raise EOFError
            self.pos += 1
            return self.data[self.pos - 1]

        def varint(self):
            shift = result = 0
            while True:
                b = self.byte()
                result |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    return result

        def avro_long(self):                       # zigzag
            n = self.varint()
            return (n >> 1) ^ -(n & 1)

        def take(self, n):
            if self.pos + n > len(self.data):
                raise EOFError
            self.pos += n
            return self.data[self.pos - n:self.pos]

        def avro_string(self):
            return self.take(self.avro_long()).decode()

    def avro_order(payload, version):
        r = Reader(payload)
        o = {"order_id": r.avro_string(), "user_id": r.avro_long(),
             "total": struct.unpack("<d", r.take(8))[0], "ts": r.avro_long(),
             "currency": "CAD", "n_items": 0}
        if version == 2:
            o["currency"] = r.avro_string()
            if r.avro_long() == 1:
                r.avro_string()
            while (count := r.avro_long()) != 0:
                for _ in range(count):
                    r.avro_string(), r.avro_long()
                o["n_items"] += count
        return o

    def proto_payment(payload):
        r, p = Reader(payload), {"amount_cents": 0, "method": 0}
        while r.pos < len(payload):
            key = r.varint()
            field, wire = key >> 3, key & 7
            value = r.varint() if wire == 0 else r.take(r.varint())
            p[field if field not in (2, 3, 4) else {2: "order_id", 3: "amount_cents", 4: "method"}[field]] = value
        return {"order_id": p["order_id"].decode(), "paid_cents": p["amount_cents"],
                "method": [None, "CARD", "CASH", "GIFT_CARD"][p["method"]]}

    state, want_dead = {}, set()
    for line in open(ORDERS):
        m = json.loads(line)
        if m["value"] is None:
            state[m["key"]] = None
            continue
        raw = base64.b64decode(m["value"])
        if raw[0] != 0:
            want_dead.add(("orders", m["offset"], "no confluent header"))
            continue
        sid = int.from_bytes(raw[1:5], "big")
        if sid not in schemas:
            want_dead.add(("orders", m["offset"], "unknown schema id"))
            continue
        try:
            state[m["key"]] = dict(avro_order(raw[5:], sid), schema_id=sid)
        except EOFError:
            want_dead.add(("orders", m["offset"], "corrupt"))
    want_orders = {k: v for k, v in state.items() if v is not None}
    want_pay = {}
    for line in open(PAYMENTS):
        m = json.loads(line)
        try:
            p = proto_payment(base64.b64decode(m["value"])[6:])
            want_pay[p["order_id"]] = p
        except (EOFError, KeyError, UnicodeDecodeError):
            want_dead.add(("payments", m["offset"], "corrupt"))

    try:
        raw_orders = read_topic(spark, ORDERS)
        assert raw_orders is not None, "read_topic() returned None: complete TODO 1"
        assert dict(raw_orders.dtypes).get("value") == "binary", (
            f"value should be BINARY (use F.unbase64), got {dict(raw_orders.dtypes).get('value')}")
        assert raw_orders.count() == sum(1 for _ in open(ORDERS)), "One row per message"

        framed = split_confluent(raw_orders)
        assert framed is not None, "split_confluent() returned None: complete TODO 2"
        for c in ("framed", "schema_id", "payload"):
            assert c in framed.columns, f"split_confluent must add {c}, got {framed.columns}"
        ids = {r["schema_id"] for r in framed.filter("framed").select("schema_id").distinct().collect()}
        assert ids == {1, 2, 7}, (
            f"Framed orders use schema ids 1, 2 and 7, got {sorted(ids)}. The id is bytes 2 to 5, "
            "big-endian: F.conv(F.hex(F.substring('value', 2, 4)), 16, 10).cast('int')")
        assert framed.filter("framed = false").count() == 1, "Exactly one order message has no Confluent header"
        first = framed.filter("offset = 0").first()
        assert bytes(first["payload"])[:1] == b"\x0c", (
            "The Avro payload starts after the 5-byte header (its first byte is the zigzag length of 'O-2001'). "
            "Use substring(value, 6)")

        decoded = decode_orders(framed, schemas)
        assert decoded is not None, "decode_orders() returned None: complete TODO 3"
        o_type = decoded.schema["o"].dataType.simpleString()
        assert o_type.startswith("struct<order_id:string,user_id:bigint,total:double,ts:timestamp,currency:string"), (
            f"o should have the newest (version 2) shape, got {o_type}. Pass the newest schema as the avroSchema option")
        v1_row = decoded.filter("offset = 0").select("o.*").first()
        assert v1_row["total"] == want_orders["O-2001"]["total"] and v1_row["currency"] == "CAD", (
            f"A version 1 message must read as version 2: total from amount (the alias), currency from the "
            f"default 'CAD'. Got {v1_row}")

        classified = classify(decoded, "o", schemas.keys())
        assert classified is not None, "classify() returned None: complete TODO 4"
        problems = {(r["offset"], r["problem"]) for r in classified.filter("problem IS NOT NULL").collect()}
        want_problems = {(off, why) for t, off, why in want_dead if t == "orders"} | {(5, "tombstone")}
        assert problems == want_problems, (
            f"Order problems should be {sorted(want_problems)}, got {sorted(problems)}. "
            "Remember that from_avro in PERMISSIVE mode returns a struct of NULLs, not NULL: test o.order_id")

        orders = current_orders(classified)
        assert orders is not None, "current_orders() returned None: complete TODO 5"
        got_orders = {r["order_id"]: r.asDict()
                      for r in orders.withColumn("ms", F.unix_millis("ts")).collect()}
        assert set(got_orders) == set(want_orders), (
            f"Current orders differ. Missing: {sorted(set(want_orders) - set(got_orders))}, "
            f"unexpected: {sorted(set(got_orders) - set(want_orders))}. A tombstone deletes its key")
        for k, want in want_orders.items():
            got = got_orders[k]
            assert got["user_id"] == want["user_id"] and round(got["total"], 2) == round(want["total"], 2), (
                f"{k}: expected user {want['user_id']} and total {want['total']}, got {got}")
            assert got["currency"] == want["currency"] and got["n_items"] == want["n_items"], (
                f"{k}: expected currency {want['currency']} and {want['n_items']} items, got {got}")
            assert got["schema_id"] == want["schema_id"], f"{k}: expected schema id {want['schema_id']}, got {got}"
            assert got["ms"] == want["ts"], (
                f"{k}: ts should be the timestamp-millis value {want['ts']} as a TIMESTAMP, got {got['ts']}")

        raw_pay = read_topic(spark, PAYMENTS)
        pay_framed = split_confluent(raw_pay, message_indexes=True)
        payments = decode_payments(pay_framed, DESC)
        assert payments is not None, "decode_payments() returned None: complete TODO 6"
        assert dict(payments.dtypes)["p"].startswith("struct<payment_id:string,order_id:string,amount_cents:bigint"), (
            f"p should be the decoded shop.Payment, got {dict(payments.dtypes)['p']}")
        zero = payments.filter("p.order_id = 'O-2004'").select("p.amount_cents").first()
        assert zero is not None and zero[0] == 0, (
            f"O-2004 was paid 0 cents. proto3 does not write zero values, so without the "
            f"emit.default.values option it reads as NULL. Got {zero}")
        pay_classified = classify(payments, "p", [3])

        table = order_table(orders, pay_classified)
        assert table is not None, "order_table() returned None: complete TODO 7"
        want_cols = ["order_id", "user_id", "total", "currency", "n_items", "ts", "paid_cents", "method", "paid"]
        assert table.columns == want_cols, f"order_table columns should be {want_cols}, got {table.columns}"
        rows = {r["order_id"]: r for r in table.collect()}
        assert len(rows) == len(want_orders), f"One row per current order ({len(want_orders)}), got {len(rows)}"
        for k in want_orders:
            p = want_pay.get(k)
            r = rows[k]
            want = (p["paid_cents"], p["method"], True) if p else (None, None, False)
            assert (r["paid_cents"], r["method"], r["paid"]) == want, (
                f"{k}: expected (paid_cents, method, paid) = {want}, got "
                f"{(r['paid_cents'], r['method'], r['paid'])}. METHOD_UNSPECIFIED should become NULL (F.nullif)")

        dead = dead_letters(classified, pay_classified)
        assert dead is not None, "dead_letters() returned None: complete TODO 8"
        got_dead = {(r["topic"], r["offset"], r["problem"]) for r in dead.collect()}
        assert got_dead == want_dead, f"Dead letters should be {sorted(want_dead)}, got {sorted(got_dead)}"
        assert dead.filter("value IS NULL").count() == 0, "Keep the raw bytes of every dead letter"

        print("Orders topic, decoded:")
        classified.select("offset", "key", "schema_id", "problem", "o.order_id", "o.total", "o.currency").show(8)
        print("Current orders with payments:")
        table.show(8, truncate=False)
        print("Dead letters:")
        dead.select("topic", "offset", "key", "problem").show(truncate=False)
        print("All tests passed!")
    finally:
        spark.stop()
