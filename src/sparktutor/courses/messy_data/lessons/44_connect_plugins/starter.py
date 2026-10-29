# spark-run: python
"""
Spark Connect Plugins - Exercise

A Spark Connect client cannot reach the JVM through Py4J, so this exercise
exposes JVM features through Connect's plugin interfaces:
  - PlanNodesPlugin (RelationPlugin): plan_nodes(df, stage) returns the analyzed,
    optimized or physical plan of any DataFrame as rows, so a Connect client can
    test plan shapes without df._jdf
  - MagicPlugin (ExpressionPlugin): has_magic(col, b"...") as a typed Column
  - NotePlugin (CommandPlugin): a command with a side effect on the server
The Java is compiled with javac and loaded into a local Spark Connect server
started by remote("local[2]"); the custom messages are protobuf messages built at
run time with descriptor_pb2, packed into google.protobuf.Any.

Complete the two TODOs:
  TODO 1  PlanNodesPlugin.transform (Java): decode the Any, plan the input relation,
          pick the stage and return the rows
  TODO 2  PlanNodesRelation.plan (Python): build the Relation with the extension
"""

import glob
import os
import subprocess
import sys
import tempfile
from pathlib import Path

JAVA = {}

# ---------------------------------------------------------------------------
# A minimal protobuf wire-format reader (complete as given).
# ---------------------------------------------------------------------------
JAVA["jplug/Wire.java"] = r'''
package jplug;

import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

/**
 * Plugins receive the serialized google.protobuf.Any as byte[]. Spark's own copy of
 * protobuf-java is shaded (org.sparkproject.connect.protobuf), so instead of depending
 * on it, this class reads the wire format directly: each field is a varint key
 * (field number << 3 | wire type) followed by a varint (type 0) or a length and that
 * many bytes (type 2: strings, bytes and embedded messages).
 */
public final class Wire {
  /** Field number -> value: byte[] for length-delimited fields, Long for varints. */
  public static Map<Integer, Object> fields(byte[] buf) {
    Map<Integer, Object> out = new HashMap<>();
    int[] pos = {0};
    while (pos[0] < buf.length) {
      long key = varint(buf, pos);
      int field = (int) (key >>> 3), type = (int) (key & 7);
      switch (type) {
        case 0 -> out.put(field, varint(buf, pos));
        case 2 -> {
          int len = (int) varint(buf, pos);
          byte[] v = new byte[len];
          System.arraycopy(buf, pos[0], v, 0, len);
          pos[0] += len;
          out.put(field, v);
        }
        case 1 -> pos[0] += 8;
        case 5 -> pos[0] += 4;
        default -> throw new IllegalArgumentException("unsupported wire type " + type);
      }
    }
    return out;
  }

  static long varint(byte[] b, int[] pos) {
    long r = 0;
    int shift = 0;
    while (true) {
      byte x = b[pos[0]++];
      r |= (long) (x & 0x7f) << shift;
      if ((x & 0x80) == 0) return r;
      shift += 7;
    }
  }

  public static String string(Map<Integer, Object> f, int n, String dflt) {
    Object v = f.get(n);
    return v == null ? dflt : new String((byte[]) v, StandardCharsets.UTF_8);
  }

  public static byte[] bytes(Map<Integer, Object> f, int n) {
    Object v = f.get(n);
    return v == null ? new byte[0] : (byte[]) v;
  }
}
'''

# ---------------------------------------------------------------------------
# The relation plugin. TODO 1 in the exercise.
# ---------------------------------------------------------------------------
JAVA["jplug/PlanNodesPlugin.java"] = r'''
package jplug;

import java.util.*;
import org.apache.spark.connect.proto.Relation;
import org.apache.spark.sql.Row;
import org.apache.spark.sql.RowFactory;
import org.apache.spark.sql.catalyst.plans.QueryPlan;
import org.apache.spark.sql.catalyst.plans.logical.LogicalPlan;
import org.apache.spark.sql.classic.Dataset;
import org.apache.spark.sql.classic.SparkSession;
import org.apache.spark.sql.connect.ConnectProtoUtils;
import org.apache.spark.sql.connect.planner.SparkConnectPlanner;
import org.apache.spark.sql.connect.plugin.RelationPlugin;
import org.apache.spark.sql.execution.QueryExecution;
import org.apache.spark.sql.execution.adaptive.AdaptiveSparkPlanExec;
import org.apache.spark.sql.types.DataTypes;
import org.apache.spark.sql.types.StructType;
import scala.jdk.javaapi.CollectionConverters;

/**
 * message jplug.PlanNodes { bytes input = 1; string stage = 2; }
 * input is a serialized spark.connect.Relation; stage is analyzed, optimized or physical.
 * Result: one row per plan node, depth first.
 */
public class PlanNodesPlugin implements RelationPlugin {
  public static final String TYPE_URL = "type.googleapis.com/jplug.PlanNodes";

  static final StructType SCHEMA = new StructType()
      .add("id", DataTypes.IntegerType, false)
      .add("parent", DataTypes.IntegerType, true)
      .add("depth", DataTypes.IntegerType, false)
      .add("node", DataTypes.StringType, false)
      .add("detail", DataTypes.StringType, false);

  @Override public Optional<LogicalPlan> transform(byte[] any, SparkConnectPlanner planner) {
    // TODO 1:
    //  a. Map<Integer, Object> a = Wire.fields(any): field 1 of an Any is the type_url, field 2 the value.
    //     If Wire.string(a, 1, "") is not TYPE_URL, return Optional.empty() (another plugin may handle it).
    //  b. Decode the value (Wire.fields(Wire.bytes(a, 2))): field 1 is the input Relation's bytes,
    //     field 2 the stage (default "optimized").
    //  c. Relation input = ConnectProtoUtils.parseRelationWithRecursionLimit(bytes, 1024);
    //     LogicalPlan child = planner.transformRelation(input);
    //  d. QueryExecution qe = Dataset.ofRows(planner.session(), child).queryExecution();
    //     choose qe.analyzed(), qe.optimizedPlan() or qe.executedPlan() by stage; for any other stage
    //     throw new IllegalArgumentException("stage must be analyzed, optimized or physical, got '" + stage + "'")
    //  e. List<Row> rows = new ArrayList<>(); walk(root, null, 0, rows);
    //     return Optional.of(planner.session().createDataFrame(rows, SCHEMA).logicalPlan());
    return Optional.empty();
  }

  /** Depth-first walk. AdaptiveSparkPlanExec hides its plan from children(), so step into it. */
  static void walk(QueryPlan<?> p, Integer parent, int depth, List<Row> rows) {
    if (p instanceof AdaptiveSparkPlanExec a) p = a.executedPlan();
    int id = rows.size();
    rows.add(RowFactory.create(id, parent, depth, p.nodeName(), p.simpleString(400)));
    for (Object c : CollectionConverters.asJava(p.children())) walk((QueryPlan<?>) c, id, depth + 1, rows);
  }
}
'''

# ---------------------------------------------------------------------------
# An expression plugin and a command plugin (complete as given).
# ---------------------------------------------------------------------------
JAVA["jplug/MagicPlugin.java"] = r'''
package jplug;

import java.util.Map;
import java.util.Optional;
import org.apache.spark.sql.catalyst.expressions.EqualTo;
import org.apache.spark.sql.catalyst.expressions.Expression;
import org.apache.spark.sql.catalyst.expressions.Literal;
import org.apache.spark.sql.catalyst.expressions.Substring;
import org.apache.spark.sql.connect.ConnectProtoUtils;
import org.apache.spark.sql.connect.planner.SparkConnectPlanner;
import org.apache.spark.sql.connect.plugin.ExpressionPlugin;
import org.apache.spark.sql.types.DataTypes;

/** message jplug.HasMagic { bytes child = 1; bytes magic = 2; }  ->  substring(child, 1, n) = magic */
public class MagicPlugin implements ExpressionPlugin {
  @Override public Optional<Expression> transform(byte[] any, SparkConnectPlanner planner) {
    Map<Integer, Object> a = Wire.fields(any);
    if (!"type.googleapis.com/jplug.HasMagic".equals(Wire.string(a, 1, ""))) return Optional.empty();
    Map<Integer, Object> m = Wire.fields(Wire.bytes(a, 2));
    Expression child = planner.transformExpression(
        ConnectProtoUtils.parseExpressionWithRecursionLimit(Wire.bytes(m, 1), 1024));
    byte[] magic = Wire.bytes(m, 2);
    Expression prefix = new Substring(child, Literal.create(1, DataTypes.IntegerType),
        Literal.create(magic.length, DataTypes.IntegerType));
    return Optional.of(new EqualTo(prefix, Literal.create(magic, DataTypes.BinaryType)));
  }
}
'''

JAVA["jplug/NotePlugin.java"] = r'''
package jplug;

import java.util.Map;
import org.apache.spark.sql.connect.planner.SparkConnectPlanner;
import org.apache.spark.sql.connect.plugin.CommandPlugin;

/** message jplug.Note { string text = 1; }  ->  stores text in the session conf jplug.note. */
public class NotePlugin implements CommandPlugin {
  @Override public boolean process(byte[] any, SparkConnectPlanner planner) {
    Map<Integer, Object> a = Wire.fields(any);
    if (!"type.googleapis.com/jplug.Note".equals(Wire.string(a, 1, ""))) return false;
    String text = Wire.string(Wire.fields(Wire.bytes(a, 2)), 1, "");
    planner.session().conf().set("jplug.note", text);
    return true;
  }
}
'''


def build_jar(java=JAVA, name="jplug"):
    """Compile the sources against pyspark's jars and package them."""
    import pyspark

    work = Path(tempfile.mkdtemp(prefix=name + "_"))
    for rel, code in java.items():
        f = work / "src" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(code)
    classes = work / "classes"
    classes.mkdir()
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
# The client side: protobuf messages built at run time, and the Connect plan nodes.
# ---------------------------------------------------------------------------
def make_messages():
    """jplug.PlanNodes, jplug.HasMagic and jplug.Note as Python message classes, without protoc."""
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

    FD = descriptor_pb2.FieldDescriptorProto
    fdp = descriptor_pb2.FileDescriptorProto(name="jplug/messages.proto", package="jplug", syntax="proto3")
    for name, fields in [("PlanNodes", [("input", FD.TYPE_BYTES), ("stage", FD.TYPE_STRING)]),
                         ("HasMagic", [("child", FD.TYPE_BYTES), ("magic", FD.TYPE_BYTES)]),
                         ("Note", [("text", FD.TYPE_STRING)])]:
        m = fdp.message_type.add(name=name)
        for number, (fname, ftype) in enumerate(fields, start=1):
            m.field.add(name=fname, number=number, type=ftype, label=FD.LABEL_OPTIONAL)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fdp)
    return {n: message_factory.GetMessageClass(pool.FindMessageTypeByName("jplug." + n))
            for n in ("PlanNodes", "HasMagic", "Note")}


MESSAGES = make_messages()


def client_classes():
    """Classes that need pyspark.sql.connect (imported only when a Connect session exists)."""
    from pyspark.sql.connect.column import Column
    from pyspark.sql.connect.dataframe import DataFrame
    from pyspark.sql.connect.expressions import Expression
    from pyspark.sql.connect.plan import LogicalPlan

    class PlanNodesRelation(LogicalPlan):
        """A Relation whose rel_type is extension: Any(jplug.PlanNodes)."""

        def __init__(self, child, stage):
            super().__init__(child)
            self._stage = stage

        def plan(self, session):
            # TODO 2: rel = self._create_proto_relation(); build MESSAGES["PlanNodes"] with
            # input = the child's Relation serialized to bytes (self._child.plan(session).SerializeToString())
            # and stage = self._stage; pack it into rel.extension (rel.extension.Pack(msg)); return rel.
            return self._child.plan(session)

    class HasMagicExpression(Expression):
        def __init__(self, child, magic):
            super().__init__()
            self._child = child
            self._magic = magic

        def to_plan(self, session):
            import pyspark.sql.connect.proto as pb

            e = pb.Expression()
            e.extension.Pack(MESSAGES["HasMagic"](child=self._child.to_plan(session).SerializeToString(),
                                                  magic=self._magic))
            return e

        def __repr__(self):
            return f"has_magic({self._child!r}, {self._magic!r})"

    def plan_nodes(df, stage="optimized"):
        """The plan of df at a stage, as a DataFrame of (id, parent, depth, node, detail)."""
        return DataFrame(PlanNodesRelation(df._plan, stage), df.sparkSession)

    def has_magic(col, magic):
        """True if the binary column starts with the bytes magic."""
        return Column(HasMagicExpression(col._expr, magic))

    def note(spark, text):
        """Run the jplug.Note command on the server."""
        import pyspark.sql.connect.proto as pb

        cmd = pb.Command()
        cmd.extension.Pack(MESSAGES["Note"](text=text))
        spark.client.execute_command(cmd)

    return plan_nodes, has_magic, note


if __name__ == "__main__":
    jar = build_jar()

    import warnings

    from pyspark.sql import SparkSession, functions as F

    # The server receives these settings when it starts. Afterwards the Connect client also
    # tries to set them on the session, which static settings refuse with a UserWarning
    # ("Failed to set spark.jars ... CANNOT_MODIFY_CONFIG"). Harmless; hide it.
    warnings.filterwarnings("ignore", message="Failed to set")

    # remote("local[2]") starts a Spark Connect server inside this Python process and connects
    # to it. Static settings given here reach the server: the jar and the three plugin lists.
    spark = (SparkSession.builder
        .appName("ConnectPlugins")
        .remote("local[2]")
        .config("spark.jars", jar)
        .config("spark.connect.extensions.relation.classes", "jplug.PlanNodesPlugin")
        .config("spark.connect.extensions.expression.classes", "jplug.MagicPlugin")
        .config("spark.connect.extensions.command.classes", "jplug.NotePlugin")
        .config("spark.ui.enabled", "false")
        .getOrCreate())
    plan_nodes, has_magic, note = client_classes()

    def nodes(df, stage="optimized"):
        return [(r.depth, r.node) for r in plan_nodes(df, stage).orderBy("id").collect()]

    try:
        assert spark.__class__.__module__ == "pyspark.sql.connect.session", (
            f"Expected a Spark Connect session, got {spark.__class__}")
        try:
            spark._jvm
            raise AssertionError("A Connect session should have no _jvm")
        except AssertionError:
            raise
        except Exception as e:
            assert "JVM_ATTRIBUTE_NOT_SUPPORTED" in str(e), str(e)[:200]

        # 1. The optimized plan of a small query, as rows
        q = spark.range(10).filter("id > 3").select((F.col("id") * 2).alias("x"))
        try:
            columns = plan_nodes(q).columns
        except Exception as e:
            if "NO_HANDLER_FOR_EXTENSION" not in str(e):
                raise
            raise AssertionError(
                "The server found no plugin for jplug.PlanNodes (NO_HANDLER_FOR_EXTENSION): "
                "PlanNodesPlugin.transform must return the rows for type_url " + repr(
                    "type.googleapis.com/jplug.PlanNodes") + " instead of Optional.empty()") from None
        assert columns == ["id", "parent", "depth", "node", "detail"], (
            f"plan_nodes(q) has columns {columns}, so the client did not send the extension. "
            "PlanNodesRelation.plan must return a Relation whose extension holds a packed jplug.PlanNodes")
        got = nodes(q)
        assert got and got[0][0] == 0, (
            f"plan_nodes returned {got}. Check that PlanNodesRelation.plan packs a jplug.PlanNodes into "
            "rel.extension and that PlanNodesPlugin.transform returns the rows")
        names = [n for _, n in got]
        assert names == ["Project", "Filter", "Range"], f"Optimized plan should be Project/Filter/Range, got {got}"
        rows = plan_nodes(q).orderBy("id").collect()
        assert rows[0].parent is None and all(r.parent == r.id - 1 for r in rows[1:]), (
            f"parent ids should link each node to the one above it: {[(r.id, r.parent) for r in rows]}")
        print("Optimized:", got)

        # 2. Every stage works, and an unknown stage gives the plugin's message
        assert [n for _, n in nodes(q, "analyzed")][0] == "Project"
        try:
            plan_nodes(q, "parsed").collect()
            raise AssertionError("stage 'parsed' should fail")
        except AssertionError:
            raise
        except Exception as e:
            assert "stage must be analyzed, optimized or physical" in str(e), str(e)[:300]

        # 3. Test plan facts from a Connect client: pushed filters and Python UDF nodes
        tmp = tempfile.mkdtemp(prefix="plugins_")
        spark.range(100).selectExpr("id", "id % 7 AS k").write.parquet(os.path.join(tmp, "t"))
        t = spark.read.parquet(os.path.join(tmp, "t")).filter("k = 3")
        scan = [r.detail for r in plan_nodes(t, "physical").collect() if r.node.startswith("Scan parquet")]
        assert scan and "PushedFilters: [IsNotNull(k), EqualTo(k,3)]" in scan[0], (
            f"The physical plan should show the pushed filter, got {scan}")
        double = F.udf(lambda v: v * 2, "long")
        py = [n for _, n in nodes(spark.range(5).select(double("id")), "physical")]
        assert any("EvalPython" in n for n in py), f"A Python UDF should appear as an EvalPython node: {py}"
        print("Physical, from the client: pushed filter seen; Python node", [n for n in py if "Python" in n])

        # 4. An extension nobody handles fails with Connect's error class
        from pyspark.sql.connect.dataframe import DataFrame as ConnectDataFrame
        from pyspark.sql.connect.plan import LogicalPlan

        class Unknown(LogicalPlan):
            def plan(self, session):
                rel = self._create_proto_relation()
                rel.extension.Pack(MESSAGES["Note"](text="not a relation"))
                return rel

        try:
            ConnectDataFrame(Unknown(None), spark).collect()
            raise AssertionError("An unhandled extension should fail")
        except AssertionError:
            raise
        except Exception as e:
            assert "NO_HANDLER_FOR_EXTENSION" in str(e), str(e)[:300]

        # 5. The expression plugin: a typed Column
        imgs = (spark.read.format("binaryFile").option("recursiveFileLookup", "true")
                .load(os.path.abspath("data/messy/images")))
        got = {os.path.basename(r.path): r.png
               for r in imgs.select("path", has_magic(F.col("content"), b"\x89PNG").alias("png")).collect()}
        want = {}
        for folder, _, files in os.walk("data/messy/images"):
            for n in files:
                with open(os.path.join(folder, n), "rb") as f:
                    want[n] = f.read(4) == b"\x89PNG"
        assert got == want, f"has_magic should be {want}, got {got}"
        print("has_magic:", dict(sorted(got.items())))

        # 6. The command plugin changes server-side session state
        note(spark, "checked by the plugins exercise")
        assert spark.conf.get("jplug.note") == "checked by the plugins exercise", spark.conf.get("jplug.note", None)
        print("Command: jplug.note =", spark.conf.get("jplug.note"))

        print("All tests passed!")
    finally:
        spark.stop()
