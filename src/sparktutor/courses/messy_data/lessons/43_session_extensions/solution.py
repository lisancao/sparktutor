# spark-run: python
"""
Catalyst Extensions: Rules and Native Functions - Solution

A SparkSessionExtensions class in Java, loaded with spark.sql.extensions:
  - is_png(bytes): a native Catalyst Expression (interpreted, CodegenFallback)
  - is_png_fast(bytes): the same check as a StaticInvoke (real code generation)
  - PngRule: an optimizer rule that replaces a Python UDF named is_png with the
    native expression, keeping the UDF's NULL behaviour
  - a check rule that rejects GROUP BY on a BINARY column
The harness compiles the Java with javac, starts a session with the jar, and
checks results, plans and edge cases.
"""

import glob
import os
import subprocess
import sys
import tempfile
from pathlib import Path

JAVA = {}

# ---------------------------------------------------------------------------
# The native expression. TODO 1 in the exercise.
# ---------------------------------------------------------------------------
JAVA["jext/IsPng.java"] = r'''
package jext;

import java.io.Serializable;
import java.util.List;
import java.util.Objects;
import org.apache.spark.sql.catalyst.InternalRow;
import org.apache.spark.sql.catalyst.analysis.TypeCheckResult;
import org.apache.spark.sql.catalyst.expressions.Expression;
import org.apache.spark.sql.catalyst.expressions.codegen.CodegenContext;
import org.apache.spark.sql.catalyst.expressions.codegen.CodegenFallback;
import org.apache.spark.sql.catalyst.expressions.codegen.ExprCode;
import org.apache.spark.sql.types.BinaryType;
import org.apache.spark.sql.types.DataType;
import org.apache.spark.sql.types.DataTypes;
import org.apache.spark.sql.types.NullType;
import scala.collection.immutable.IndexedSeq;
import scala.collection.immutable.Seq;
import scala.jdk.javaapi.CollectionConverters;

/**
 * is_png(bytes): true if the bytes start with the 8-byte PNG signature, false if
 * not, NULL for a NULL input (the usual SQL rule for a function of one argument).
 *
 * A Scala case class gets equals, hashCode, Serializable and the Product methods
 * for free. A Java subclass of Expression writes them by hand.
 */
public class IsPng extends Expression implements CodegenFallback, Serializable {
  static final byte[] SIG = {(byte) 0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};
  private final Expression child;

  public IsPng(Expression child) { this.child = child; }

  /** The check itself, also called directly by the StaticInvoke version. */
  public static boolean check(byte[] b) {
    if (b.length < SIG.length) return false;
    for (int i = 0; i < SIG.length; i++) if (b[i] != SIG[i]) return false;
    return true;
  }

  /** Interpreted evaluation: BinaryType values are byte[]; a NULL child gives NULL. */
  @Override public Object eval(InternalRow row) {
    Object v = child.eval(row);
    return v == null ? null : check((byte[]) v);
  }

  /** CodegenFallback: generated code calls eval(). Java must ask for the trait's method by name. */
  @Override public ExprCode doGenCode(CodegenContext ctx, ExprCode ev) {
    return CodegenFallback.super.doGenCode(ctx, ev);
  }

  /**
   * Runs during analysis: a wrong type fails with DATATYPE_MISMATCH, not a ClassCastException
   * in a task. NullType is the type of an untyped NULL literal, as in is_png(NULL).
   */
  @Override public TypeCheckResult checkInputDataTypes() {
    DataType t = child.dataType();
    if (t instanceof BinaryType || t instanceof NullType) return TypeCheckResult.TypeCheckSuccess$.MODULE$;
    return new TypeCheckResult.TypeCheckFailure("is_png expects BINARY, got " + child.dataType().simpleString());
  }

  @Override public DataType dataType() { return DataTypes.BooleanType; }
  @Override public boolean nullable() { return child.nullable(); }
  @Override public String prettyName() { return "is_png"; }

  // Tree plumbing that a Scala case class would generate.
  @Override public Seq<Expression> children() { return CollectionConverters.asScala(List.of(child)).toSeq(); }
  @Override public Expression withNewChildrenInternal(IndexedSeq<Expression> c) { return new IsPng(c.apply(0)); }
  @Override public int productArity() { return 1; }
  @Override public Object productElement(int n) {
    if (n == 0) return child;
    throw new IndexOutOfBoundsException(n);
  }
  @Override public boolean canEqual(Object o) { return o instanceof IsPng; }
  @Override public boolean equals(Object o) { return o instanceof IsPng p && p.child.equals(child); }
  @Override public int hashCode() { return Objects.hash("is_png", child); }
}
'''

# ---------------------------------------------------------------------------
# The optimizer rule. TODO 2 in the exercise.
# ---------------------------------------------------------------------------
JAVA["jext/PngRule.java"] = r'''
package jext;

import java.util.List;
import org.apache.spark.sql.catalyst.expressions.Coalesce;
import org.apache.spark.sql.catalyst.expressions.Expression;
import org.apache.spark.sql.catalyst.expressions.Literal;
import org.apache.spark.sql.catalyst.expressions.PythonUDF;
import org.apache.spark.sql.catalyst.plans.logical.LogicalPlan;
import org.apache.spark.sql.catalyst.rules.Rule;
import org.apache.spark.sql.types.DataTypes;
import scala.Function1;
import scala.jdk.javaapi.CollectionConverters;
import scala.runtime.AbstractPartialFunction;

/**
 * Replaces a Python UDF called is_png by the native expression. It runs in the
 * optimizer's operator batches, before "Extract Python UDFs" turns Python UDFs
 * into BatchEvalPython / ArrowEvalPython nodes, so a rewritten UDF never reaches
 * a Python worker.
 */
public class PngRule extends Rule<LogicalPlan> {
  static int rewrites = 0;
  public static int rewrites() { return rewrites; }

  /**
   * Only a UDF we know: named is_png, deterministic, one BINARY argument, BOOLEAN
   * result. Anything else might mean something different, so leave it alone.
   */
  static boolean matches(Expression e) {
    if (!(e instanceof PythonUDF u)) return false;
    return u.name().equals("is_png")
        && u.udfDeterministic()
        && u.dataType().equals(DataTypes.BooleanType)
        && u.children().size() == 1
        && u.children().apply(0).dataType().equals(DataTypes.BinaryType);
  }

  /**
   * The Python is_png returns False for None; the native is_png returns NULL.
   * coalesce(is_png(x), false) keeps the UDF's answer for every input.
   */
  static Expression replacement(PythonUDF u) {
    Expression child = u.children().apply(0);
    return new Coalesce(CollectionConverters.asScala(
        List.<Expression>of(new IsPng(child), Literal.FalseLiteral())).toSeq());
  }

  @Override public LogicalPlan apply(LogicalPlan plan) {
    return (LogicalPlan) plan.transformAllExpressions(new AbstractPartialFunction<Expression, Expression>() {
      @Override public boolean isDefinedAt(Expression e) { return matches(e); }

      @Override @SuppressWarnings("unchecked")
      public <A1 extends Expression, B1> B1 applyOrElse(A1 e, Function1<A1, B1> otherwise) {
        if (!matches(e)) return otherwise.apply(e);
        rewrites++;
        return (B1) replacement((PythonUDF) e);
      }
    });
  }
}
'''

# ---------------------------------------------------------------------------
# The extension entry point named in spark.sql.extensions. Complete as given.
# ---------------------------------------------------------------------------
JAVA["jext/Extensions.java"] = r'''
package jext;

import java.util.List;
import org.apache.spark.sql.SparkSessionExtensions;
import org.apache.spark.sql.catalyst.FunctionIdentifier;
import org.apache.spark.sql.catalyst.expressions.Expression;
import org.apache.spark.sql.catalyst.expressions.ExpressionInfo;
import org.apache.spark.sql.catalyst.expressions.objects.StaticInvoke;
import org.apache.spark.sql.catalyst.plans.logical.Aggregate;
import org.apache.spark.sql.types.AbstractDataType;
import org.apache.spark.sql.types.BinaryType;
import org.apache.spark.sql.types.DataTypes;
import scala.Function1;
import scala.Option;
import scala.Tuple3;
import scala.collection.immutable.Seq;
import scala.jdk.javaapi.CollectionConverters;
import scala.runtime.AbstractFunction1;
import scala.runtime.BoxedUnit;

/** spark.sql.extensions=jext.Extensions: Spark calls apply once per new session. */
public class Extensions extends AbstractFunction1<SparkSessionExtensions, BoxedUnit> {
  @Override public BoxedUnit apply(SparkSessionExtensions ext) {
    // 1. is_png(bytes): our own Expression class
    ext.injectFunction(new Tuple3<>(
        new FunctionIdentifier("is_png"),
        new ExpressionInfo(IsPng.class.getName(), null, "is_png",
            "is_png(bytes) - true if bytes start with the PNG signature", ""),
        (Function1<Seq<Expression>, Expression>) args -> {
          if (args.size() != 1) throw new IllegalArgumentException("is_png takes 1 argument, got " + args.size());
          return new IsPng(args.apply(0));
        }));

    // 2. is_png_fast(bytes): a StaticInvoke of IsPng.check, which Spark compiles into generated code
    ext.injectFunction(new Tuple3<>(
        new FunctionIdentifier("is_png_fast"),
        new ExpressionInfo(IsPng.class.getName(), "is_png_fast"),
        (Function1<Seq<Expression>, Expression>) args -> new StaticInvoke(
            IsPng.class, DataTypes.BooleanType, "check", args,
            CollectionConverters.asScala(List.<AbstractDataType>of(DataTypes.BinaryType)).toSeq(),
            true, true, true, Option.empty())));

    // 3. The optimizer rule
    ext.injectOptimizerRule(session -> new PngRule());

    // 4. A check rule: runs on every analyzed plan and throws to reject it
    ext.injectCheckRule(session -> plan -> {
      plan.foreach(node -> {
        if (node instanceof Aggregate a) {
          a.groupingExpressions().foreach(g -> {
            if (g.resolved() && g.dataType() instanceof BinaryType)
              throw new IllegalArgumentException("Grouping by a BINARY column (" + g.sql()
                  + ") compares whole file contents; group by sha2(" + g.sql() + ", 256) instead");
            return BoxedUnit.UNIT;
          });
        }
        return BoxedUnit.UNIT;
      });
      return BoxedUnit.UNIT;
    });
    return BoxedUnit.UNIT;
  }
}
'''


def build_jar(java=JAVA, name="jext"):
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


PNG_SIG = b"\x89PNG\r\n\x1a\n"


if __name__ == "__main__":
    jar = build_jar()

    from pyspark.sql import SparkSession, functions as F

    spark = (SparkSession.builder
        .appName("SessionExtensions")
        .master("local[2]")
        .config("spark.jars", jar)
        .config("spark.sql.extensions", "jext.Extensions")
        .config("spark.ui.enabled", "false")
        .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    def plan(df):
        return df._jdf.queryExecution().executedPlan().toString()

    def python_nodes(df):
        return [l.strip() for l in plan(df).splitlines() if "EvalPython" in l]

    # Python UDFs the rule should and should not touch. The function name is the UDF name.
    @F.udf("boolean")
    def is_png(b):
        return b is not None and bytes(b[:8]) == PNG_SIG

    @F.udf("boolean")
    def looks_like_png(b):
        return b is not None and bytes(b[:8]) == PNG_SIG

    try:
        # 1. The native function on literals: true, false, too short, and NULL
        try:
            got = spark.sql(
                "SELECT is_png(X'89504E470D0A1A0A') AS sig, is_png(X'89504E470D0A1A0A0000') AS longer, "
                "is_png(X'89504E470D0A1A') AS short, is_png(X'') AS empty, "
                "is_png(X'FF504E470D0A1A0A') AS wrong, is_png(CAST(NULL AS BINARY)) AS null_in, "
                "is_png(NULL) AS untyped_null"
            ).first().asDict()
        except Exception as e:
            if "NullPointerException" not in str(e):
                raise
            raise AssertionError(
                "is_png on non-NULL literals crashed with a NullPointerException in generated code. "
                "nullable() follows the child, so for a non-NULL input Spark trusts eval() to return a "
                "Boolean: return check((byte[]) v) when the child value v is not null") from None
        want = {"sig": True, "longer": True, "short": False, "empty": False, "wrong": False, "null_in": None,
                "untyped_null": None}
        assert got == want, (
            f"is_png on literals should give {want}, got {got}. IsPng.check compares the first 8 bytes "
            "with SIG (shorter input is false); eval returns null when the child is null")
        print("is_png on literals:", got)

        # 2. A wrong type fails during analysis, with Spark's error class
        try:
            spark.sql("SELECT is_png('not binary')").collect()
            raise AssertionError("is_png('not binary') should fail analysis")
        except AssertionError:
            raise
        except Exception as e:
            assert "DATATYPE_MISMATCH" in str(e), f"Expected DATATYPE_MISMATCH, got {str(e)[:200]}"

        # 3. On real files, from Python with call_function
        root = os.path.abspath("data/messy/images")
        imgs = spark.read.format("binaryFile").option("recursiveFileLookup", "true").load(root)
        got = {os.path.basename(r.path): r.png
               for r in imgs.select("path", F.call_function("is_png", "content").alias("png")).collect()}
        want, contents = {}, set()
        for folder, _, names in os.walk(root):
            for n in names:
                with open(os.path.join(folder, n), "rb") as f:
                    data = f.read()
                want[n] = data[:8] == PNG_SIG
                contents.add(data)
        assert got == want, f"is_png over data/messy/images should be {want}, got {got}"
        print("is_png over images:", dict(sorted(got.items())))

        # 4. The rule: a Python UDF named is_png becomes native, with the UDF's NULL behaviour
        null_row = spark.createDataFrame([(None,)], "content binary")
        files = imgs.select("content").unionByName(null_row)
        df = files.select(is_png("content").alias("png"))
        assert not python_nodes(df), (
            f"PngRule should remove the Python UDF, but the plan still has {python_nodes(df)}. "
            "Check PngRule.matches and PngRule.replacement")
        assert "coalesce(is_png(" in plan(df), (
            "The rewritten UDF should be coalesce(is_png(content), false), plan:\n" + plan(df))
        got = sorted((r.png for r in df.collect()), key=repr)
        expected = sorted(list(want.values()) + [False], key=repr)
        assert got == expected, (
            f"After the rewrite results must equal the Python UDF's, including False for the NULL row. "
            f"Expected {expected}, got {got}")
        flt = imgs.filter(is_png("content")).select("path")
        assert not python_nodes(flt), f"A filter on is_png should be rewritten too: {python_nodes(flt)}"
        print("Rewritten:", [l.strip() for l in plan(df).splitlines() if "coalesce" in l][0][:60],
              "| rewrites so far:", spark._jvm.jext.PngRule.rewrites())

        # 5. UDFs that are not exactly is_png keep running in Python
        keep = {
            "another name": looks_like_png("content"),
            "a string result": F.udf(lambda b: "yes", "string")("content"),
            "nondeterministic": is_png.asNondeterministic()("content"),
        }
        for why, col in keep.items():
            q = files.select(col.alias("x"))
            assert python_nodes(q), f"PngRule must not rewrite a UDF with {why}; plan:\n{plan(q)}"
        print("Left alone: another name, a string result, a nondeterministic UDF")

        # 6. CodegenFallback blocks whole-stage codegen, StaticInvoke does not
        slow = plan(imgs.select(F.call_function("is_png", "content")))
        fast = plan(imgs.select(F.call_function("is_png_fast", "content")))
        assert "*(1) Project" not in slow and "*(1) Project" in fast, (
            f"Expected no WholeStageCodegen for is_png and one for is_png_fast:\n{slow}\n{fast}")
        print("Codegen:", fast.splitlines()[0][:70])

        # 7. The check rule rejects GROUP BY on a BINARY column, and allows the hash
        try:
            imgs.groupBy("content").count().collect()
            raise AssertionError("GROUP BY content should be rejected by the check rule")
        except AssertionError:
            raise
        except Exception as e:
            assert "sha2" in str(e), f"Unexpected error for GROUP BY content: {str(e)[:200]}"
        n = imgs.groupBy(F.sha2("content", 256)).count().count()
        assert n == len(contents), f"GROUP BY sha2(content, 256) should give {len(contents)} groups, got {n}"
        print("Check rule: GROUP BY content rejected, GROUP BY sha2(content, 256) allowed")

        print("All tests passed!")
    finally:
        spark.stop()
