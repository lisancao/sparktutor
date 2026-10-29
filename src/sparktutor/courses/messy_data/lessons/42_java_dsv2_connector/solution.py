# spark-run: python
"""
A DSv2 Connector in Java - Solution

`jdocs` is the docs source from the intermediate level, rewritten against
Spark's Java connector API (DataSource V2). It lists a folder on the driver,
pushes filters, required columns, LIMIT and COUNT(*) into the listing, and
reads PNG headers in tasks. The Java sources live in the JAVA dict below; the
harness compiles them with javac against pyspark's own jars, starts a session
with the jar on spark.jars, and compares jdocs with a Python data source that
reads the same folder.
"""

import datetime
import glob
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

JAVA = {}

# ---------------------------------------------------------------------------
# The entry point: TableProvider (DSv2) + DataSourceRegister (short name).
# ---------------------------------------------------------------------------
JAVA["jdocs/DocsSource.java"] = r'''
package jdocs;

import java.util.Map;
import org.apache.spark.sql.connector.catalog.Table;
import org.apache.spark.sql.connector.catalog.TableProvider;
import org.apache.spark.sql.connector.expressions.Transform;
import org.apache.spark.sql.sources.DataSourceRegister;
import org.apache.spark.sql.types.DataTypes;
import org.apache.spark.sql.types.StructType;
import org.apache.spark.sql.util.CaseInsensitiveStringMap;

/** spark.read.format("jdocs") finds this class through META-INF/services. */
public class DocsSource implements TableProvider, DataSourceRegister {
  public static final StructType SCHEMA = new StructType()
      .add("path", DataTypes.StringType, false)
      .add("name", DataTypes.StringType, false)
      .add("kind", DataTypes.StringType, false)
      .add("size", DataTypes.LongType, false)
      .add("modified", DataTypes.TimestampType, false)
      .add("width", DataTypes.IntegerType, true)
      .add("height", DataTypes.IntegerType, true);

  @Override public String shortName() { return "jdocs"; }

  @Override public StructType inferSchema(CaseInsensitiveStringMap options) { return SCHEMA; }

  @Override public Table getTable(StructType schema, Transform[] partitioning,
                                  Map<String, String> properties) {
    return new DocsTable(schema);
  }
}
'''

JAVA["jdocs/DocsTable.java"] = r'''
package jdocs;

import java.util.EnumSet;
import java.util.Set;
import org.apache.spark.sql.connector.catalog.SupportsRead;
import org.apache.spark.sql.connector.catalog.TableCapability;
import org.apache.spark.sql.connector.read.ScanBuilder;
import org.apache.spark.sql.types.StructType;
import org.apache.spark.sql.util.CaseInsensitiveStringMap;

public class DocsTable implements SupportsRead {
  private final StructType schema;
  DocsTable(StructType schema) { this.schema = schema; }

  @Override public String name() { return "jdocs"; }
  @Override public StructType schema() { return schema; }
  @Override public Set<TableCapability> capabilities() { return EnumSet.of(TableCapability.BATCH_READ); }

  /** Called once per query: a fresh builder, so no pushdown state leaks between queries. */
  @Override public ScanBuilder newScanBuilder(CaseInsensitiveStringMap options) {
    String path = options.get("path");
    if (path == null) throw new IllegalArgumentException("option 'path' is required: the folder to read");
    return new DocsScanBuilder(path, options.getInt("partitions", 2), schema);
  }
}
'''

JAVA["jdocs/Audit.java"] = r'''
package jdocs;

import java.util.concurrent.atomic.AtomicInteger;

/** Counters a test reads through spark._jvm. In local mode the driver and executors are one JVM. */
public final class Audit {
  static final AtomicInteger OPENED = new AtomicInteger();    // files opened by DocsReader
  static final AtomicInteger LISTINGS = new AtomicInteger();  // folder listings by build()
  public static void reset() { OPENED.set(0); LISTINGS.set(0); }
  public static int opened() { return OPENED.get(); }
  public static int listings() { return LISTINGS.get(); }
}
'''

JAVA["jdocs/FileEntry.java"] = r'''
package jdocs;

import java.io.IOException;
import java.io.InputStream;
import java.io.Serializable;
import java.io.UncheckedIOException;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;

/** One listed file: everything the planner knows without opening it. Serializable: it travels in tasks. */
public final class FileEntry implements Serializable {
  public final String path, name, kind;
  public final long size, modifiedMicros;

  FileEntry(Path p, BasicFileAttributes a) {
    this.path = p.toAbsolutePath().normalize().toString();
    this.name = p.getFileName().toString();
    this.kind = kindOf(name);
    this.size = a.size();
    this.modifiedMicros = a.lastModifiedTime().to(TimeUnit.MICROSECONDS);
  }

  static final Map<String, String> KINDS = Map.of(
      ".png", "image", ".wav", "audio", ".pdf", "pdf", ".eml", "email", ".md", "text",
      ".txt", "text", ".log", "log", ".json", "json", ".xml", "xml");

  static String kindOf(String name) {
    int dot = name.lastIndexOf('.');
    return dot < 0 ? "other" : KINDS.getOrDefault(name.substring(dot).toLowerCase(Locale.ROOT), "other");
  }

  /** Every regular file under root, sorted by path. Reads file-system metadata only. */
  static List<FileEntry> list(String root) {
    Path dir = Paths.get(root);
    if (!Files.isDirectory(dir))
      throw new IllegalArgumentException("option 'path' must be an existing folder, got '" + root + "'");
    List<FileEntry> out = new ArrayList<>();
    try (Stream<Path> s = Files.walk(dir)) {
      for (Path p : (Iterable<Path>) s::iterator) {
        BasicFileAttributes a = Files.readAttributes(p, BasicFileAttributes.class);
        if (a.isRegularFile()) out.add(new FileEntry(p, a));
      }
    } catch (IOException e) { throw new UncheckedIOException(e); }
    out.sort(Comparator.comparing(f -> f.path));
    return out;
  }

  /** PNG width and height from the first 24 bytes, or null if the bytes are not a PNG. */
  static int[] pngSize(String path) throws IOException {
    Audit.OPENED.incrementAndGet();
    byte[] h = new byte[24];
    int n;
    try (InputStream in = Files.newInputStream(Paths.get(path))) { n = in.readNBytes(h, 0, 24); }
    byte[] sig = {(byte) 0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};
    if (n < 24 || !Arrays.equals(Arrays.copyOf(h, 8), sig)
        || h[12] != 'I' || h[13] != 'H' || h[14] != 'D' || h[15] != 'R') return null;
    ByteBuffer b = ByteBuffer.wrap(h, 16, 8);   // big-endian, like the PNG spec
    return new int[] {b.getInt(), b.getInt()};
  }
}
'''

# ---------------------------------------------------------------------------
# Filters: the V2 Predicate API. TODO 1 in the exercise.
# ---------------------------------------------------------------------------
JAVA["jdocs/Filters.java"] = r'''
package jdocs;

import java.io.Serializable;
import java.util.*;
import org.apache.spark.sql.connector.expressions.Expression;
import org.apache.spark.sql.connector.expressions.Literal;
import org.apache.spark.sql.connector.expressions.NamedReference;
import org.apache.spark.sql.connector.expressions.filter.Predicate;
import org.apache.spark.unsafe.types.UTF8String;

/** The predicates jdocs takes over. Every one is decided from listing metadata, before any file opens. */
public class Filters implements Serializable {
  Set<String> kinds = null;                            // null means any kind
  final List<String> nameSuffixes = new ArrayList<>();
  final List<Object[]> sizeTests = new ArrayList<>();  // {operator, Long value}

  static final Set<String> NEVER_NULL = Set.of("path", "name", "kind", "size", "modified");

  /** The column a predicate child names, or null if it is not a plain top-level column. */
  static String column(Expression e) {
    if (e instanceof NamedReference r && r.fieldNames().length == 1) return r.fieldNames()[0];
    return null;
  }

  /** A literal child as a plain Java value. Strings arrive as UTF8String, not String. */
  static Object value(Expression e) {
    if (!(e instanceof Literal<?> l)) return null;
    Object v = l.value();
    return v instanceof UTF8String u ? u.toString() : v;
  }

  /**
   * Returns true if jdocs takes over p. Spark then stops evaluating p, so
   * matches() must apply it exactly. Return false for anything else.
   */
  boolean accept(Predicate p) {
    Expression[] c = p.children();
    String col = c.length > 0 ? column(c[0]) : null;
    if (col == null) return false;
    switch (p.name()) {
      case "IS_NOT_NULL":
        return NEVER_NULL.contains(col);              // always true for these columns
      case "=":
        if (col.equals("kind") && value(c[1]) instanceof String s) { keepKinds(Set.of(s)); return true; }
        return sizeTest(col, "=", c[1]);
      case "IN": {
        if (!col.equals("kind")) return false;
        Set<String> s = new HashSet<>();
        for (int i = 1; i < c.length; i++) {
          if (!(value(c[i]) instanceof String v)) return false;
          s.add(v);
        }
        keepKinds(s);
        return true;
      }
      case "ENDS_WITH":
        if (col.equals("name") && value(c[1]) instanceof String s) { nameSuffixes.add(s); return true; }
        return false;
      case ">": case ">=": case "<": case "<=":
        return sizeTest(col, p.name(), c[1]);
      default:
        return false;
    }
  }

  private void keepKinds(Set<String> s) {
    if (kinds == null) kinds = new HashSet<>(s); else kinds.retainAll(s);
  }

  private boolean sizeTest(String col, String op, Expression lit) {
    if (!col.equals("size") || !(value(lit) instanceof Long v)) return false;
    sizeTests.add(new Object[] {op, v});
    return true;
  }

  boolean matches(FileEntry f) {
    if (kinds != null && !kinds.contains(f.kind)) return false;
    for (String s : nameSuffixes) if (!f.name.endsWith(s)) return false;
    for (Object[] t : sizeTests) {
      long v = (Long) t[1];
      boolean ok = switch ((String) t[0]) {
        case "=" -> f.size == v;
        case ">" -> f.size > v;
        case ">=" -> f.size >= v;
        case "<" -> f.size < v;
        default -> f.size <= v;
      };
      if (!ok) return false;
    }
    return true;
  }
}
'''

# ---------------------------------------------------------------------------
# The scan builder: every SupportsPushDown* mix-in. TODO 2 in the exercise.
# ---------------------------------------------------------------------------
JAVA["jdocs/DocsScanBuilder.java"] = r'''
package jdocs;

import java.util.*;
import org.apache.spark.sql.connector.expressions.Expression;
import org.apache.spark.sql.connector.expressions.aggregate.AggregateFunc;
import org.apache.spark.sql.connector.expressions.aggregate.Aggregation;
import org.apache.spark.sql.connector.expressions.aggregate.CountStar;
import org.apache.spark.sql.connector.expressions.filter.Predicate;
import org.apache.spark.sql.connector.read.*;
import org.apache.spark.sql.types.StructType;

/** Spark pushes in this order: filters, aggregate, limit, then column pruning. Then build(). */
public class DocsScanBuilder implements SupportsPushDownV2Filters, SupportsPushDownRequiredColumns,
    SupportsPushDownLimit, SupportsPushDownAggregates {

  private final String root;
  private final int maxPartitions;
  private StructType required;
  private final Filters filters = new Filters();
  private final List<Predicate> pushed = new ArrayList<>();
  private int limit = -1;
  private boolean countStar = false;
  private boolean groupByKind = false;

  DocsScanBuilder(String root, int maxPartitions, StructType schema) {
    this.root = root; this.maxPartitions = maxPartitions; this.required = schema;
  }

  /** Keep what Filters accepts; return the rest, unchanged, for Spark to evaluate after the scan. */
  @Override public Predicate[] pushPredicates(Predicate[] predicates) {
    List<Predicate> rest = new ArrayList<>();
    for (Predicate p : predicates) {
      if (filters.accept(p)) pushed.add(p); else rest.add(p);
    }
    return rest.toArray(new Predicate[0]);
  }

  @Override public Predicate[] pushedPredicates() { return pushed.toArray(new Predicate[0]); }

  /** Only the columns the query uses. readSchema() and the reader must honour it. */
  @Override public void pruneColumns(StructType requiredSchema) { this.required = requiredSchema; }

  /** One file is one row and every pushed filter is exact, so a limit on the listing is complete. */
  @Override public boolean pushLimit(int limit) { this.limit = limit; return true; }
  @Override public boolean isPartiallyPushed() { return false; }

  /** COUNT(*) alone, or COUNT(*) GROUP BY kind: both answerable from the listing. */
  private static boolean answerable(Aggregation agg) {
    AggregateFunc[] fs = agg.aggregateExpressions();
    Expression[] gs = agg.groupByExpressions();
    if (fs.length != 1 || !(fs[0] instanceof CountStar)) return false;
    return gs.length == 0 || (gs.length == 1 && "kind".equals(Filters.column(gs[0])));
  }

  /** true: Spark removes its own Aggregate and trusts our rows as the final answer. */
  @Override public boolean supportCompletePushDown(Aggregation agg) { return answerable(agg); }

  @Override public boolean pushAggregation(Aggregation agg) {
    if (!answerable(agg)) return false;
    countStar = true;
    groupByKind = agg.groupByExpressions().length == 1;
    return true;
  }

  @Override public Scan build() {
    Audit.LISTINGS.incrementAndGet();
    List<FileEntry> files = new ArrayList<>();
    for (FileEntry f : FileEntry.list(root)) if (filters.matches(f)) files.add(f);
    if (countStar) return new CountScan(files, groupByKind, pushed);
    if (limit >= 0 && files.size() > limit) files = new ArrayList<>(files.subList(0, limit));
    return new DocsScan(files, required, maxPartitions, pushed, limit);
  }
}
'''

JAVA["jdocs/DocsScan.java"] = r'''
package jdocs;

import java.util.*;
import org.apache.spark.sql.connector.expressions.filter.Predicate;
import org.apache.spark.sql.connector.read.*;
import org.apache.spark.sql.types.StructType;

/** The planned read. Scan, Batch and statistics in one class, which is common for small sources. */
public class DocsScan implements Scan, Batch, SupportsReportStatistics {
  private final List<FileEntry> files;
  private final StructType schema;
  private final int maxPartitions;
  private final List<Predicate> pushed;
  private final int limit;

  DocsScan(List<FileEntry> files, StructType schema, int maxPartitions, List<Predicate> pushed, int limit) {
    this.files = files; this.schema = schema; this.maxPartitions = maxPartitions;
    this.pushed = pushed; this.limit = limit;
  }

  @Override public StructType readSchema() { return schema; }

  /** What explain() prints after "BatchScan jdocs[...]". Spark prints nothing about pushdown for you. */
  @Override public String description() {
    return "jdocs[files=" + files.size() + ", pushed=" + pushed + (limit >= 0 ? ", limit=" + limit : "") + "]";
  }

  @Override public Batch toBatch() { return this; }

  /** Largest file first into the lightest group, as in the Python docs source. */
  @Override public InputPartition[] planInputPartitions() {
    int n = Math.max(1, Math.min(maxPartitions, files.size()));
    List<List<FileEntry>> groups = new ArrayList<>();
    long[] totals = new long[n];
    for (int i = 0; i < n; i++) groups.add(new ArrayList<>());
    List<FileEntry> bySize = new ArrayList<>(files);
    bySize.sort(Comparator.comparingLong((FileEntry f) -> -f.size).thenComparing(f -> f.path));
    for (FileEntry f : bySize) {
      int best = 0;
      for (int i = 1; i < n; i++) if (totals[i] < totals[best]) best = i;
      groups.get(best).add(f);
      totals[best] += f.size;
    }
    List<InputPartition> out = new ArrayList<>();
    for (List<FileEntry> g : groups) if (!g.isEmpty()) out.add(new DocsPartition(g));
    return out.toArray(new InputPartition[0]);
  }

  @Override public PartitionReaderFactory createReaderFactory() { return new DocsReaderFactory(schema); }

  /** Reported after pushdown, so the optimizer sees the filtered row count (join and broadcast choices). */
  @Override public Statistics estimateStatistics() {
    long rows = files.size();
    long bytes = rows * 120L;   // a rough width for one row of metadata columns
    return new Statistics() {
      public OptionalLong sizeInBytes() { return OptionalLong.of(bytes); }
      public OptionalLong numRows() { return OptionalLong.of(rows); }
    };
  }
}
'''

JAVA["jdocs/CountScan.java"] = r'''
package jdocs;

import java.util.*;
import org.apache.spark.sql.catalyst.InternalRow;
import org.apache.spark.sql.catalyst.expressions.GenericInternalRow;
import org.apache.spark.sql.connector.expressions.filter.Predicate;
import org.apache.spark.sql.connector.read.LocalScan;
import org.apache.spark.sql.types.DataTypes;
import org.apache.spark.sql.types.StructType;
import org.apache.spark.unsafe.types.UTF8String;

/** COUNT(*) [GROUP BY kind] from the listing, on the driver: no task runs and no file is opened. */
public class CountScan implements LocalScan {
  private final List<FileEntry> files;
  private final boolean byKind;
  private final List<Predicate> pushed;

  CountScan(List<FileEntry> files, boolean byKind, List<Predicate> pushed) {
    this.files = files; this.byKind = byKind; this.pushed = pushed;
  }

  /** Grouping columns first, then the aggregates, in the order of the Aggregation. */
  @Override public StructType readSchema() {
    StructType s = new StructType();
    if (byKind) s = s.add("kind", DataTypes.StringType, false);
    return s.add("count", DataTypes.LongType, false);
  }

  @Override public InternalRow[] rows() {
    if (!byKind) return new InternalRow[] {new GenericInternalRow(new Object[] {(long) files.size()})};
    TreeMap<String, Long> counts = new TreeMap<>();
    for (FileEntry f : files) counts.merge(f.kind, 1L, Long::sum);
    List<InternalRow> out = new ArrayList<>();
    counts.forEach((k, v) -> out.add(new GenericInternalRow(new Object[] {UTF8String.fromString(k), v})));
    return out.toArray(new InternalRow[0]);
  }

  @Override public String description() {
    return "jdocs COUNT(*)" + (byKind ? " GROUP BY kind" : "") + " from listing, pushed=" + pushed;
  }
}
'''

JAVA["jdocs/DocsPartition.java"] = r'''
package jdocs;

import java.util.List;
import org.apache.spark.sql.connector.read.InputPartition;

/** Serialized into each task: listing metadata, never file contents. */
public class DocsPartition implements InputPartition {
  final List<FileEntry> files;
  DocsPartition(List<FileEntry> files) { this.files = files; }
}
'''

JAVA["jdocs/DocsReaderFactory.java"] = r'''
package jdocs;

import org.apache.spark.sql.catalyst.InternalRow;
import org.apache.spark.sql.connector.read.InputPartition;
import org.apache.spark.sql.connector.read.PartitionReader;
import org.apache.spark.sql.connector.read.PartitionReaderFactory;
import org.apache.spark.sql.types.StructType;

/** Serialized to executors once per task; creates the reader there. */
public class DocsReaderFactory implements PartitionReaderFactory {
  private final StructType schema;
  DocsReaderFactory(StructType schema) { this.schema = schema; }
  @Override public PartitionReader<InternalRow> createReader(InputPartition p) {
    return new DocsReader(((DocsPartition) p).files, schema);
  }
}
'''

# ---------------------------------------------------------------------------
# The reader: InternalRow in the pruned schema. TODO 3 in the exercise.
# ---------------------------------------------------------------------------
JAVA["jdocs/DocsReader.java"] = r'''
package jdocs;

import java.io.IOException;
import java.util.List;
import org.apache.spark.sql.catalyst.InternalRow;
import org.apache.spark.sql.catalyst.expressions.GenericInternalRow;
import org.apache.spark.sql.connector.read.PartitionReader;
import org.apache.spark.sql.types.StructType;
import org.apache.spark.unsafe.types.UTF8String;

/** Runs in a task. next() advances, get() returns the current row. */
public class DocsReader implements PartitionReader<InternalRow> {
  private final List<FileEntry> files;
  private final String[] columns;      // the read schema after pruning, in order
  private final boolean needsHeader;   // open PNGs only if width or height was asked for
  private int i = -1;
  private InternalRow current;

  DocsReader(List<FileEntry> files, StructType schema) {
    this.files = files;
    this.columns = schema.fieldNames();
    boolean h = false;
    for (String c : columns) h |= c.equals("width") || c.equals("height");
    this.needsHeader = h;
  }

  @Override public boolean next() throws IOException {
    if (++i >= files.size()) return false;
    FileEntry f = files.get(i);
    int[] wh = (needsHeader && f.kind.equals("image")) ? FileEntry.pngSize(f.path) : null;
    Object[] values = new Object[columns.length];
    for (int c = 0; c < columns.length; c++) {
      values[c] = switch (columns[c]) {
        case "path" -> UTF8String.fromString(f.path);   // StringType: UTF8String
        case "name" -> UTF8String.fromString(f.name);
        case "kind" -> UTF8String.fromString(f.kind);
        case "size" -> f.size;                          // LongType: a long
        case "modified" -> f.modifiedMicros;            // TimestampType: microseconds since the epoch
        case "width" -> wh == null ? null : wh[0];      // IntegerType: an int, or null
        case "height" -> wh == null ? null : wh[1];
        default -> throw new IllegalStateException("unknown column " + columns[c]);
      };
    }
    current = new GenericInternalRow(values);
    return true;
  }

  @Override public InternalRow get() { return current; }
  @Override public void close() {}
}
'''

# The service file that maps the short name "jdocs" to the class.
RESOURCES = {
    "META-INF/services/org.apache.spark.sql.sources.DataSourceRegister": "jdocs.DocsSource\n",
}


def build_jar(java=JAVA, resources=RESOURCES, name="jdocs"):
    """Compile the sources against pyspark's jars and package them with the resources."""
    import pyspark

    work = Path(tempfile.mkdtemp(prefix=name + "_"))
    for rel, code in java.items():
        f = work / "src" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(code)
    classes = work / "classes"
    for rel, text in resources.items():
        f = classes / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    jars = glob.glob(os.path.join(os.path.dirname(pyspark.__file__), "jars", "*.jar"))
    try:
        r = subprocess.run(["javac", "--release", "17", "-d", str(classes), "-cp", os.pathsep.join(jars),
                            *map(str, sorted((work / "src").rglob("*.java")))],
                           capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit("javac not found: this lesson needs a JDK 17 (not only a JRE) on the PATH")
    if r.returncode:
        sys.exit("javac failed, fix the Java above:\n" + r.stderr)
    jar = work / f"{name}.jar"
    subprocess.run(["jar", "cf", str(jar), "-C", str(classes), "."], check=True)
    return str(jar)


# ---------------------------------------------------------------------------
# The reference: the same rows from a Python data source (the intermediate level's docs source).
# ---------------------------------------------------------------------------
KINDS = {".png": "image", ".wav": "audio", ".pdf": "pdf", ".eml": "email", ".md": "text",
         ".txt": "text", ".log": "log", ".json": "json", ".xml": "xml"}
SCHEMA = ("path string, name string, kind string, size long, modified timestamp, "
          "width int, height int")


def kind_of(name):
    return KINDS.get(os.path.splitext(name)[1].lower(), "other")


def py_rows(root):
    """Plain Python rows for root, the expected answer for every check."""
    rows = []
    for folder, _, names in os.walk(root):
        for n in names:
            p = os.path.abspath(os.path.join(folder, n))
            st = os.stat(p)
            w = h = None
            if kind_of(n) == "image":
                with open(p, "rb") as f:
                    head = f.read(24)
                if len(head) == 24 and head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
                    w, h = struct.unpack(">II", head[16:24])
            modified = (datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
                        + datetime.timedelta(microseconds=st.st_mtime_ns // 1000))
            rows.append({"path": p, "name": n, "kind": kind_of(n), "size": st.st_size,
                         "modified": modified, "width": w, "height": h})
    return sorted(rows, key=lambda r: r["path"])


def make_pydocs():
    from pyspark.sql.datasource import DataSource, DataSourceReader

    class PyDocs(DataSource):
        @classmethod
        def name(cls):
            return "pydocs"

        def schema(self):
            return SCHEMA

        def reader(self, schema):
            return PyDocsReader(self.options["path"])

    class PyDocsReader(DataSourceReader):
        def __init__(self, root):
            self.root = root

        def read(self, partition):
            for r in py_rows(self.root):
                yield tuple(r.values())

    return PyDocs


if __name__ == "__main__":
    jar = build_jar()

    from pyspark.sql import SparkSession, functions as F

    spark = (SparkSession.builder
        .appName("JavaDSv2Connector")
        .master("local[2]")
        .config("spark.jars", jar)
        .config("spark.ui.enabled", "false")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    spark.dataSource.register(make_pydocs())
    Audit = spark._jvm.jdocs.Audit

    root = os.path.abspath("data/messy")
    expected = py_rows(root)
    pngs = sorted(r["name"] for r in expected if r["name"].endswith(".png"))

    def jdocs():
        return spark.read.format("jdocs").option("path", root).load()

    def plan(df):
        """The physical plan as text, from the JVM object (classic sessions only)."""
        return df._jdf.queryExecution().executedPlan().toString()

    def scan_line(df):
        return next((l for l in plan(df).splitlines() if "BatchScan jdocs" in l or "LocalTableScan" in l), "")

    def spark_filters(df):
        return [l.strip() for l in plan(df).splitlines() if "Filter " in l and "Scan" not in l]

    def names(rows):
        return sorted(r.name for r in rows)

    try:
        # 1. The full read: the same rows as the Python data source
        full = jdocs()
        assert full.schema.simpleString().startswith("struct<path:string,name:string,kind:string,size:bigint"), (
            f"Unexpected schema {full.schema.simpleString()}: DocsSource.inferSchema should return SCHEMA")
        n = full.count()
        assert n == len(expected), (
            f"jdocs returned {n} rows for {len(expected)} files. DocsReader.next() must return true once "
            "per file and false at the end")
        py = spark.read.format("pydocs").option("path", root).load()
        diff = full.exceptAll(py).union(py.exceptAll(full)).limit(5).collect()
        assert not diff, (
            f"jdocs and the Python source disagree, for example on {diff[:2]}. Check the value types in "
            "DocsReader.next(): UTF8String for strings, long micros for modified, null width for non-PNGs")
        print(f"Full read: {n} rows, identical to the Python data source")

        # 2. Column pruning: the scan produces only the columns the query uses, and opens nothing
        Audit.reset()
        df = jdocs().select("name", "size")
        rows = df.collect()
        line = scan_line(df)
        assert "jdocs[name#" in line and "path#" not in line and "width#" not in line, (
            f"The scan should output only name and size, got: {line}. pruneColumns must keep requiredSchema "
            "and DocsReader must build rows in that schema")
        assert Audit.opened() == 0, f"select('name', 'size') opened {Audit.opened()} files; it needs none"
        print("Column pruning:", line.strip()[:70], "...")

        # 3. kind = 'image': pushed, no Filter left in Spark, and only the PNGs are opened
        Audit.reset()
        df = jdocs().filter(F.col("kind") == "image").select("name", "width", "height")
        rows = df.collect()
        assert names(rows) == pngs, f"kind = 'image' should return {pngs}, got {names(rows)}"
        assert "kind = 'image'" in scan_line(df) and not spark_filters(df), (
            f"kind = 'image' should be pushed and Spark should not filter again. Scan: {scan_line(df)}; "
            f"Spark filters: {spark_filters(df)}. Handle '=' on kind in Filters.accept")
        assert Audit.opened() == len(pngs), (
            f"Only the {len(pngs)} PNGs should be opened, jdocs opened {Audit.opened()} files")
        sizes = {r.name: (r.width, r.height) for r in rows}
        assert sizes["red_16x8.png"] == (16, 8) and sizes["corrupt.png"] == (None, None), (
            f"PNG sizes are wrong: {sizes}")

        # 4. IN, ENDS_WITH and size comparisons decide files from metadata only
        cases = [
            (F.col("kind").isin("pdf", "email"), lambda r: r["kind"] in ("pdf", "email")),
            (F.col("name").endswith(".log"), lambda r: r["name"].endswith(".log")),
            ((F.col("size") > 4000) & (F.col("size") <= 30000), lambda r: 4000 < r["size"] <= 30000),
        ]
        for cond, keep in cases:
            Audit.reset()
            df = jdocs().filter(cond).select("name", "size")
            got = names(df.collect())
            want = sorted(r["name"] for r in expected if keep(r))
            assert got == want, f"Filter {cond} should return {want}, got {got}"
            assert not spark_filters(df), (
                f"Filter {cond} should be fully pushed, but Spark still filters: {spark_filters(df)}")
            assert Audit.opened() == 0, f"Filter {cond} opened {Audit.opened()} files; metadata is enough"
        print("Pushed: kind IN, name ENDS_WITH, size comparisons; no file opened")

        # 5. What jdocs cannot decide stays in Spark, and the answer is still right
        df = jdocs().filter((F.col("kind") == "image") & (F.col("width") > 12))
        got = names(df.collect())
        want = sorted(r["name"] for r in expected if r["kind"] == "image" and (r["width"] or 0) > 12)
        assert got == want, f"kind = 'image' AND width > 12 should return {want}, got {got}"
        assert any("width" in l for l in spark_filters(df)), (
            f"width > 12 needs the file's bytes: return it to Spark. Spark filters: {spark_filters(df)}")
        df = jdocs().filter("kind = 'audio' OR size < 100")
        want = sorted(r["name"] for r in expected if r["kind"] == "audio" or r["size"] < 100)
        assert names(df.collect()) == want, "An OR predicate must be returned to Spark, not dropped"
        print("Returned to Spark: width > 12 and the OR:", spark_filters(df)[0][:60])

        # 6. COUNT(*) from the listing: no task, no file opened
        Audit.reset()
        df = jdocs().filter("kind = 'image'").groupBy().count()
        value = df.collect()[0][0]
        assert value == len(pngs), f"COUNT(*) of images should be {len(pngs)}, got {value}"
        assert "LocalTableScan" in plan(df) and "BatchScan" not in plan(df), (
            "COUNT(*) should be answered by CountScan (a LocalTableScan in the plan), got:\n" + plan(df))
        assert Audit.opened() == 0, f"COUNT(*) opened {Audit.opened()} files"
        by_kind = {r["kind"]: r["count"] for r in jdocs().groupBy("kind").count().collect()}
        want = {}
        for r in expected:
            want[r["kind"]] = want.get(r["kind"], 0) + 1
        assert by_kind == want, f"COUNT(*) GROUP BY kind should be {want}, got {by_kind}"
        df = jdocs().groupBy("kind").agg(F.sum("size"))
        assert "BatchScan" in plan(df), "sum(size) cannot be answered by CountScan; pushAggregation must refuse it"
        print("COUNT(*) pushed:", value, "images; GROUP BY kind:", dict(sorted(by_kind.items())))

        # 7. LIMIT on the listing
        Audit.reset()
        df = jdocs().select("name").limit(3)
        assert len(df.collect()) == 3 and "limit=3" in scan_line(df), (
            f"limit(3) should be pushed into the listing, scan: {scan_line(df)}")
        print("LIMIT pushed:", scan_line(df).strip()[-40:])

        print("All tests passed!")
    finally:
        spark.stop()
