"""
Documents to Rows - Starter Code

Turn three kinds of documents into rows:
1. parse_emails: one row per .eml file, parsed with the standard library
   `email` package inside a Python UDF
2. pdf_pages: one row per PDF page, produced by a Python UDTF
3. markdown_chunks: one row per paragraph of each Markdown file, with
   built-in functions only
4. documents: the three results in one common shape, ready for search
"""

from pyspark.sql import SparkSession, functions as F


EMAIL_TYPE = "struct<sender:string, subject:string, sent:timestamp, body:string>"


def parse_eml_bytes(content):
    """Parse the bytes of one e-mail into (sender, subject, sent, body).

    Plain Python, so you can test it without Spark. Missing headers become
    None instead of raising, so one odd file cannot fail the whole job.
    """
    from email import policy
    from email.parser import BytesParser

    if content is None:
        return None
    msg = BytesParser(policy=policy.default).parsebytes(content)
    date = msg["Date"]
    body = msg.get_body(preferencelist=("plain",))
    return (
        str(msg["From"]) if msg["From"] else None,
        str(msg["Subject"]) if msg["Subject"] else None,
        date.datetime if date is not None and date.datetime is not None else None,
        body.get_content().strip() if body is not None else None,
    )


class PdfPages:
    """A UDTF handler: one output row (page, text) per page of a simple PDF."""

    def eval(self, content):
        import re

        if content is None:
            return
        # Each page of the sample PDFs draws one string: BT ... (text) Tj ET
        for number, raw in enumerate(re.findall(rb"BT .*?\((.*?)\) Tj ET", content, re.S), start=1):
            yield number, raw.decode("latin-1")


def parse_emails(spark, folder):
    """One row per e-mail: file, sender, subject, sent, body, order_id."""
    # TODO 1: create a UDF from parse_eml_bytes with EMAIL_TYPE (here, after
    #   the session exists), read *.eml from `folder` with binaryFile, select
    #   _metadata.file_name as "file" and the parsed struct, expand it with
    #   "m.*", and add order_id: the digits after "order " in body, as int
    return None


def pdf_pages(spark, folder):
    """One row per PDF page: file, page, text."""
    # TODO 2: create a UDTF from PdfPages with returnType "page int, text string",
    #   read *.pdf with binaryFile, select file and content, then
    #   .lateralJoin(<udtf>(F.col("content").outer())) and drop content
    return None


def markdown_chunks(spark, folder):
    """One row per paragraph: file, title, chunk (1, 2, ...), text."""
    # TODO 3: read f"{folder}/*.md" with spark.read.text(..., wholetext=True),
    #   take the title from the "# " heading line, split the text on blank
    #   lines, keep only non-empty pieces that are not headings, posexplode,
    #   number chunks from 1, and trim spaces AND newlines from the text
    return None


def documents(emails, pages, chunks):
    """Union the three into: doc, part, kind, title, text."""
    # TODO 4: select each input into doc, part, kind, title, text
    #   (emails: part 1, kind "email", title = subject, text = body;
    #    pages: part = page, kind "pdf", title NULL as string;
    #    chunks: part = chunk, kind "markdown") and unionByName them
    return None


# ---- Test harness ----
if __name__ == "__main__":
    spark = (SparkSession.builder
             .appName("DocumentsToRows")
             .master("local[*]")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    try:
        # 1. E-mails
        emails = parse_emails(spark, "data/messy/mail")
        assert emails is not None, "parse_emails() returned None"
        expected_cols = ["file", "sender", "subject", "sent", "body", "order_id"]
        assert emails.columns == expected_cols, f"parse_emails columns should be {expected_cols}, got {emails.columns}"
        rows = {r["file"]: r for r in emails.collect()}
        assert len(rows) == 4, f"Expected 4 e-mails, got {len(rows)}: {sorted(rows)}"
        subjects = sorted(r["subject"] for r in rows.values())
        assert subjects == ["Broken item", "Broken item", "Broken item", "Where is my order?"], (
            f"Subjects should come from the Subject header, got {subjects}")
        t2 = rows["ticket_2.eml"]
        assert t2["sender"] == "customer2@example.com", f"ticket_2 sender is wrong: {t2['sender']}"
        assert dict(emails.dtypes)["sent"] == "timestamp", (
            f"sent should be a timestamp, got {dict(emails.dtypes)['sent']}")
        # Format in SQL: it uses the session time zone (UTC), while collect()
        # would hand back a naive datetime in this machine's local time zone
        sent = emails.filter("file = 'ticket_2.eml'").select(
            F.date_format("sent", "yyyy-MM-dd HH:mm").alias("s")).first()["s"]
        assert sent == "2026-10-03 09:00", (
            f"ticket_2 was sent 2026-10-03 09:00 UTC; got {sent}. Return the Date header's "
            ".datetime (a timezone-aware datetime) from the UDF")
        assert t2["body"] == "Hello, order 1002 has a problem. Please help.", (
            f"body should be the stripped plain-text part, got {t2['body']!r}")
        orders = sorted(r["order_id"] for r in rows.values())
        assert orders == [1000, 1001, 1002, 1003], f"order_id should be pulled from the body, got {orders}"

        # A file that is not an e-mail must not crash the job
        # (plain Python: no Spark needed to test a parser)
        bad = parse_eml_bytes(b"\x89PNG not a mail")
        assert bad is not None and bad[1] is None and bad[2] is None, (
            f"parse_eml_bytes should return None fields for bytes without headers, got {bad}")
        assert list(PdfPages().eval(b"no pages here")) == [], "PdfPages should yield nothing for a non-PDF"

        # 2. PDF pages
        pages = pdf_pages(spark, "data/messy/pdf")
        assert pages is not None, "pdf_pages() returned None"
        assert pages.columns == ["file", "page", "text"], f"pdf_pages columns should be file, page, text; got {pages.columns}"
        got = sorted((r["file"], r["page"], r["text"]) for r in pages.collect())
        expected = [("invoice_1001.pdf", 1, "Invoice 1001 total 42.50 CAD"),
                    ("invoice_1001.pdf", 2, "Thank you for shopping"),
                    ("invoice_1002.pdf", 1, "Invoice 1002 total 17.00 CAD")]
        assert got == expected, f"Expected 3 pages from 2 PDFs:\n  {expected}\ngot\n  {got}"

        # 3. Markdown chunks
        chunks = markdown_chunks(spark, "data/messy/docs")
        assert chunks is not None, "markdown_chunks() returned None"
        assert chunks.columns == ["file", "title", "chunk", "text"], (
            f"markdown_chunks columns should be file, title, chunk, text; got {chunks.columns}")
        chunks = chunks.cache()
        per_file = {r["file"]: r["n"] for r in chunks.groupBy("file").agg(F.count("*").alias("n")).collect()}
        assert per_file == {"privacy.md": 3, "returns.md": 3, "shipping.md": 3, "warranty.md": 3}, (
            f"Each policy has a heading and 3 paragraphs, so 3 chunks per .md file; got {per_file}. "
            "Read only *.md, use wholetext=True, and drop the heading and empty pieces")
        first = chunks.filter("file = 'shipping.md' AND chunk = 1").first()
        assert first is not None, "No chunk 1 for shipping.md: number chunks from 1"
        assert first["title"] == "Shipping policy", f"title should come from the '# ' heading, got {first['title']!r}"
        assert first["text"].startswith("Standard shipping takes 3 to 5 business days."), (
            f"chunk 1 of shipping.md should be its first paragraph, got {first['text']!r}")
        assert not any(r["text"].startswith("#") or r["text"] != r["text"].strip() for r in chunks.collect()), (
            "chunks should be trimmed and contain no '#' heading lines")

        # 4. One table of documents
        docs = documents(emails, pages, chunks)
        assert docs is not None, "documents() returned None"
        assert docs.columns == ["doc", "part", "kind", "title", "text"], (
            f"documents columns should be doc, part, kind, title, text; got {docs.columns}")
        kinds = {r["kind"]: r["n"] for r in docs.groupBy("kind").agg(F.count("*").alias("n")).collect()}
        assert kinds == {"email": 4, "pdf": 3, "markdown": 12}, f"Rows per kind should be email 4, pdf 3, markdown 12; got {kinds}"

        # The Markdown files repeat each paragraph: hashing finds the duplicates
        unique = docs.select("doc", F.sha2("text", 256).alias("h")).distinct().count()
        assert unique == 11, (
            f"Expected 11 distinct (doc, text) pairs (4 e-mails, 3 pages, 1 per policy), got {unique}")
        print(f"Parts: {docs.count()}, distinct (doc, text) pairs: {unique}")

        print("E-mails:")
        emails.orderBy("file").show(truncate=False)
        print("PDF pages:")
        pages.orderBy("file", "page").show(truncate=False)
        print("Documents:")
        docs.orderBy("kind", "doc", "part").show(25, truncate=60)
        print("All tests passed!")
    finally:
        spark.stop()
