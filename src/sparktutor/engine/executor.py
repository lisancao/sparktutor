"""Spark code execution engine with three-mode graceful degradation."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from sparktutor.config.settings import Settings


# Spark Declarative Pipelines source files define datasets with decorators that
# only work inside a pipeline run, so they are executed via `spark-pipelines`.
_SDP_IMPORT = re.compile(
    r"^\s*(from\s+pyspark\s+import\s+pipelines\b|import\s+pyspark\.pipelines\b"
    r"|from\s+pyspark\.pipelines\s+import\b)",
    re.MULTILINE,
)
# A lesson can ask for validation without writing data: `# spark-pipelines: dry-run`
_SDP_DRY_RUN = re.compile(r"^\s*#\s*spark-pipelines:\s*dry-run\s*$", re.MULTILINE)
# A lesson can ask for connectors that pyspark does not ship: `# spark-connectors: delta`
_CONNECTORS = re.compile(r"^\s*#\s*spark-connectors:\s*(.+?)\s*$", re.MULTILINE)

# A lesson whose script builds its own session with static settings (spark.jars,
# spark.sql.extensions) asks to run as plain Python instead of under spark-submit,
# which would start the JVM before the script runs: `# spark-run: python`
_RUN_WITH_PYTHON = re.compile(r"^\s*#\s*spark-run:\s*python\s*$", re.MULTILINE)

MAVEN_CENTRAL = "https://repo1.maven.org/maven2"


@dataclass(frozen=True)
class Connector:
    """Jars (Maven Central paths) and confs that make a connector available.

    Jars go through --jars, not --packages: in Spark 4.2.0, spark-pipelines
    does not expose --packages jars to pipeline code (DATA_SOURCE_NOT_FOUND).
    static_conf is applied at launch; session_conf goes in the pipeline spec's
    configuration block for pipelines (and --conf for spark-submit).
    """
    jars: tuple[str, ...]
    static_conf: tuple[tuple[str, str], ...] = ()
    session_conf: tuple[tuple[str, str], ...] = ()


CONNECTORS = {
    "delta": Connector(
        jars=(
            "io/delta/delta-spark_4.2_2.13/4.4.1/delta-spark_4.2_2.13-4.4.1.jar",
            "io/delta/delta-storage/4.4.1/delta-storage-4.4.1.jar",
        ),
        static_conf=(
            ("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension"),
            ("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog"),
        ),
    ),
    "kafka": Connector(
        jars=(
            "org/apache/spark/spark-sql-kafka-0-10_2.13/4.2.0/spark-sql-kafka-0-10_2.13-4.2.0.jar",
            "org/apache/spark/spark-token-provider-kafka-0-10_2.13/4.2.0/"
            "spark-token-provider-kafka-0-10_2.13-4.2.0.jar",
            "org/apache/kafka/kafka-clients/3.9.2/kafka-clients-3.9.2.jar",
            "org/apache/commons/commons-pool2/2.13.1/commons-pool2-2.13.1.jar",
        ),
    ),
    # Spark's own test catalog with MERGE support, published in the
    # spark-catalyst tests jar. In memory only: it stands in for a table format
    # until one with a Spark 4.2 build supports row-level operations.
    # Avro itself ships with pyspark; only the Spark module is missing.
    "avro": Connector(
        jars=("org/apache/spark/spark-avro_2.13/4.2.0/spark-avro_2.13-4.2.0.jar",),
    ),
    # The module shades protobuf-java, so it needs no other jar.
    "protobuf": Connector(
        jars=("org/apache/spark/spark-protobuf_2.13/4.2.0/spark-protobuf_2.13-4.2.0.jar",),
    ),
    "test-catalog": Connector(
        jars=("org/apache/spark/spark-catalyst_2.13/4.2.0/spark-catalyst_2.13-4.2.0-tests.jar",),
        session_conf=(
            ("spark.sql.catalog.mem",
             "org.apache.spark.sql.connector.catalog.SharedTablesInMemoryRowLevelOperationTableCatalog"),
        ),
    ),
}


def requested_connectors(code: str) -> list[str]:
    """Connector names an exercise asks for, in order, without duplicates."""
    names: list[str] = []
    for line in _CONNECTORS.findall(code):
        for name in re.split(r"[,\s]+", line.strip()):
            if name and name not in names:
                names.append(name)
    return names


def fetch_jars(names: list[str], cache_dir: Path) -> list[Path]:
    """Download the connectors' jars into cache_dir once and return their paths."""
    import urllib.request

    paths = []
    for name in names:
        if name not in CONNECTORS:
            raise ValueError(
                f"Unknown connector '{name}' in '# spark-connectors:'. "
                f"Known: {', '.join(sorted(CONNECTORS))}"
            )
        for maven_path in CONNECTORS[name].jars:
            target = cache_dir / Path(maven_path).name
            if not target.exists():
                cache_dir.mkdir(parents=True, exist_ok=True)
                partial = target.with_suffix(".part")
                urllib.request.urlretrieve(f"{MAVEN_CENTRAL}/{maven_path}", partial)
                partial.rename(target)
            paths.append(target)
    return paths


def connector_args(names: list[str], jars: list[str], in_pipeline: bool) -> list[str]:
    """spark-submit / spark-pipelines options for the given connectors."""
    if not names:
        return []
    args = ["--jars", ",".join(jars)]
    for name in names:
        connector = CONNECTORS[name]
        confs = connector.static_conf if in_pipeline else connector.static_conf + connector.session_conf
        for key, value in confs:
            args += ["--conf", f"{key}={value}"]
    return args


def runs_with_python(code: str) -> bool:
    """True if the exercise asks to run as plain Python (it starts its own JVM)."""
    return bool(_RUN_WITH_PYTHON.search(code))


def is_pipeline_source(code: str) -> bool:
    """True if the code is a Spark Declarative Pipelines definitions file."""
    return bool(_SDP_IMPORT.search(code))


SAMPLE_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Printed after a successful local pipeline run so students can see what each
# dataset ended up containing. Datasets named check_* are lesson assertions.
_PREVIEW_SCRIPT = """
import sys
from pathlib import Path
from pyspark.sql import SparkSession

warehouse = Path(sys.argv[1])
tables = sorted(
    p for p in warehouse.glob("**/*")
    if p.is_dir() and not p.name.startswith(("_", ".", "__spark_autocdc"))
    and not p.name.endswith(".db") and not p.name.startswith("check_")
    and any(p.glob("*.parquet"))
)
if not tables:
    sys.exit(0)
spark = SparkSession.builder.master("local[1]").appName("sparktutor-preview").getOrCreate()
spark.sparkContext.setLogLevel("ERROR")
for path in tables:
    name = path.relative_to(warehouse).as_posix().replace(".db/", ".")
    # A Delta table's directory also holds superseded parquet files.
    fmt = "delta" if (path / "_delta_log").is_dir() else "parquet"
    df = spark.read.format(fmt).load(str(path))
    print(f"\\n=== {name} ({df.count()} rows) ===")
    df.show(10, truncate=False)
spark.stop()
"""


def write_pipeline_project(code: str, root: Path, storage_root: str | None = None) -> Path:
    """Lay out a one-file pipeline project under root and return its spec path.

    The sample dataset is copied to root/data so exercises can read it with
    relative paths; spark-pipelines runs with root as its working directory.
    """
    session_conf = [
        conf
        for name in requested_connectors(code) if name in CONNECTORS
        for conf in CONNECTORS[name].session_conf
    ]
    transformations = root / "transformations"
    transformations.mkdir(parents=True, exist_ok=True)
    (transformations / "exercise.py").write_text(code)
    if SAMPLE_DATA_DIR.is_dir():
        shutil.copytree(SAMPLE_DATA_DIR, root / "data", dirs_exist_ok=True)
    storage = storage_root or f"file://{root}/storage"
    spec = root / "spark-pipeline.yml"
    spec.write_text(
        "name: sparktutor_exercise\n"
        "libraries:\n"
        "  - glob:\n"
        "      include: transformations/**\n"
        f"storage: {storage}\n"
        "configuration:\n"
        "  spark.sql.shuffle.partitions: \"4\"\n"
        # Fail fast: an exercise with a bug should report it, not retry with backoff.
        "  spark.sql.pipelines.maxFlowRetryAttempts: \"0\"\n"
        + "".join(f"  {key}: \"{value}\"\n" for key, value in session_conf)
    )
    return spec


def write_script_project(code: str, root: Path) -> Path:
    """Write a script exercise to root/exercise.py next to a copy of the sample data.

    The script runs with root as its working directory, so it can read the
    sample files with relative paths such as "data/messy/logs".
    """
    root.mkdir(parents=True, exist_ok=True)
    script = root / "exercise.py"
    script.write_text(code)
    if SAMPLE_DATA_DIR.is_dir():
        shutil.copytree(SAMPLE_DATA_DIR, root / "data", dirs_exist_ok=True)
    return script


def pipeline_command(code: str) -> str:
    """The spark-pipelines subcommand an exercise asks for."""
    return "dry-run" if _SDP_DRY_RUN.search(code) else "run"


def spark_bin(name: str) -> str:
    """Find a Spark launcher, preferring the one installed next to this interpreter."""
    candidate = Path(sys.executable).parent / name
    if candidate.exists():
        return str(candidate)
    return shutil.which(name) or name


def spark_env() -> dict[str, str]:
    """Environment for local Spark launchers.

    The pip launchers locate pyspark with `python3` from PATH, which is not this
    interpreter when a virtualenv is used without being activated (as the VS
    Code extension does), so point them at this interpreter.
    """
    env = {**os.environ}
    env.setdefault("PYSPARK_PYTHON", sys.executable)
    return env


class ExecMode(str, Enum):
    LAKEHOUSE = "lakehouse"
    LOCAL = "local"
    DRY_RUN = "dry_run"
    DATABRICKS = "databricks"


@dataclass
class ExecResult:
    mode: ExecMode
    exit_code: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class Executor:
    def __init__(self, settings: Optional[Settings] = None, force_dry_run: bool = False):
        self.settings = settings or Settings.load()
        self._force_dry_run = force_dry_run
        self._detected_mode: Optional[ExecMode] = None

    async def detect_mode(self) -> ExecMode:
        """Detect the best available execution mode."""
        if self._force_dry_run:
            return ExecMode.DRY_RUN

        configured = self.settings.execution_mode
        if configured.value != "auto":
            return ExecMode(configured.value)

        # Check for lakehouse-stack docker container
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "ps", "--filter",
                f"name={self.settings.docker.container_name}",
                "--format", "{{.Names}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            if self.settings.docker.container_name in stdout.decode():
                return ExecMode.LAKEHOUSE
        except (FileNotFoundError, asyncio.TimeoutError):
            pass

        # Check for Databricks Spark Connect
        if os.environ.get("SPARK_REMOTE") or self.settings.databricks.build_spark_remote():
            return ExecMode.DATABRICKS

        # Check for local spark-submit
        try:
            proc = await asyncio.create_subprocess_exec(
                spark_bin("spark-submit"), "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=spark_env(),
            )
            await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode == 0:
                return ExecMode.LOCAL
        except (FileNotFoundError, asyncio.TimeoutError):
            pass

        return ExecMode.DRY_RUN

    async def execute(
        self,
        code: str,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> ExecResult:
        """Execute PySpark code and return results."""
        mode = self._detected_mode or await self.detect_mode()
        self._detected_mode = mode

        if mode == ExecMode.DRY_RUN:
            return self._dry_run(code)
        elif mode == ExecMode.LAKEHOUSE:
            return await self._lakehouse_exec(code, on_output)
        elif mode == ExecMode.DATABRICKS:
            return await self._databricks_exec(code, on_output)
        else:
            return await self._local_exec(code, on_output)

    async def _connector_jars(self, code: str) -> tuple[list[str], list[Path]]:
        """Connectors the exercise asks for and their cached jar paths."""
        names = requested_connectors(code)
        if not names:
            return [], []
        jars = await asyncio.to_thread(fetch_jars, names, self.settings.data_dir / "jars")
        return names, jars

    @staticmethod
    def _connector_error(mode: ExecMode, error: Exception) -> ExecResult:
        return ExecResult(
            mode=mode, exit_code=1, stdout="",
            stderr=f"[sparktutor] Could not set up connectors: {error}",
        )

    def _dry_run(self, code: str) -> ExecResult:
        """Syntax check only; no Spark execution."""
        import ast
        try:
            ast.parse(code)
            return ExecResult(
                mode=ExecMode.DRY_RUN, exit_code=0,
                stdout="[dry-run] Syntax OK", stderr="",
            )
        except SyntaxError as e:
            return ExecResult(
                mode=ExecMode.DRY_RUN, exit_code=1,
                stdout="", stderr=f"SyntaxError: {e.msg} (line {e.lineno})",
            )

    async def _lakehouse_exec(
        self, code: str, on_output: Optional[Callable[[str], None]] = None,
    ) -> ExecResult:
        """Execute via docker exec on the lakehouse Spark master container."""
        container = self.settings.docker.container_name
        if is_pipeline_source(code):
            return await self._lakehouse_pipeline_exec(code, on_output)
        if runs_with_python(code):
            return ExecResult(
                mode=ExecMode.LAKEHOUSE, exit_code=1, stdout="",
                stderr=("[sparktutor] This exercise starts its own local Spark session "
                        "('# spark-run: python'). Switch the execution mode to local."),
            )
        try:
            extra = await self._lakehouse_connector_args(code, in_pipeline=False)
        except (OSError, ValueError) as e:
            return self._connector_error(ExecMode.LAKEHOUSE, e)

        # A unique directory per run: the script plus the sample data
        with tempfile.TemporaryDirectory(prefix="sparktutor_") as tmp:
            local_root = Path(tmp)
            remote_root = f"/tmp/{local_root.name}"
            write_script_project(code, local_root)
            cp_proc = await asyncio.create_subprocess_exec(
                "docker", "cp", str(local_root), f"{container}:{remote_root}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await cp_proc.communicate()

        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-w", remote_root, container,
            "/opt/spark/bin/spark-submit",
            "--master", self.settings.docker.spark_master_url,
            *extra,
            f"{remote_root}/exercise.py",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        return await self._stream_process(proc, ExecMode.LAKEHOUSE, on_output)

    async def _lakehouse_connector_args(self, code: str, in_pipeline: bool) -> list[str]:
        """Copy the exercise's connector jars into the container; return launch options."""
        names, jars = await self._connector_jars(code)
        if not names:
            return []
        container = self.settings.docker.container_name
        remote_dir = "/tmp/sparktutor_jars"
        mk = await asyncio.create_subprocess_exec(
            "docker", "exec", container, "mkdir", "-p", remote_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await mk.communicate()
        for jar in jars:
            cp = await asyncio.create_subprocess_exec(
                "docker", "cp", str(jar), f"{container}:{remote_dir}/{jar.name}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await cp.communicate()
        return connector_args(names, [f"{remote_dir}/{jar.name}" for jar in jars], in_pipeline)

    async def _lakehouse_pipeline_exec(
        self, code: str, on_output: Optional[Callable[[str], None]] = None,
    ) -> ExecResult:
        """Run a pipeline definitions file with spark-pipelines inside the container."""
        container = self.settings.docker.container_name
        try:
            extra = await self._lakehouse_connector_args(code, in_pipeline=True)
        except (OSError, ValueError) as e:
            return self._connector_error(ExecMode.LAKEHOUSE, e)
        with tempfile.TemporaryDirectory(prefix="sparktutor_sdp_") as tmp:
            local_root = Path(tmp)
            remote_root = f"/tmp/{local_root.name}"
            write_pipeline_project(code, local_root, storage_root=f"file://{remote_root}/storage")
            cp_proc = await asyncio.create_subprocess_exec(
                "docker", "cp", str(local_root), f"{container}:{remote_root}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await cp_proc.communicate()

        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-w", remote_root, container,
            # No --master: spark-pipelines always runs against Spark Connect
            # (a local server unless --remote is given) and rejects it.
            "/opt/spark/bin/spark-pipelines", *extra, pipeline_command(code), "--spec", f"{remote_root}/spark-pipeline.yml",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return await self._stream_process(proc, ExecMode.LAKEHOUSE, on_output)

    async def _local_pipeline_exec(
        self, code: str, on_output: Optional[Callable[[str], None]] = None,
    ) -> ExecResult:
        """Run a pipeline definitions file with a local spark-pipelines."""
        try:
            names, jars = await self._connector_jars(code)
        except (OSError, ValueError) as e:
            return self._connector_error(ExecMode.LOCAL, e)
        jar_paths = [str(jar) for jar in jars]
        with tempfile.TemporaryDirectory(prefix="sparktutor_sdp_") as tmp:
            root = Path(tmp)
            spec = write_pipeline_project(code, root)
            command = pipeline_command(code)
            proc = await asyncio.create_subprocess_exec(
                spark_bin("spark-pipelines"),
                *connector_args(names, jar_paths, in_pipeline=True),
                command, "--spec", str(spec),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=spark_env(),
                cwd=str(root),
            )
            result = await self._stream_process(proc, ExecMode.LOCAL, on_output)
            if result.success and command == "run":
                preview = await self._preview_tables(
                    root / "spark-warehouse", on_output,
                    connector_args(names, jar_paths, in_pipeline=False),
                )
                result.stdout = "\n".join(filter(None, [result.stdout, preview]))
            return result

    async def _preview_tables(
        self, warehouse: Path, on_output: Optional[Callable[[str], None]] = None,
        extra_args: Optional[list[str]] = None,
    ) -> str:
        """Show the contents of the tables a pipeline run wrote."""
        if not warehouse.is_dir():
            return ""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
            tmp.write(_PREVIEW_SCRIPT)
            script = tmp.name
        proc = await asyncio.create_subprocess_exec(
            spark_bin("spark-submit"), *(extra_args or []), script, str(warehouse),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=spark_env(),
        )
        result = await self._stream_process(proc, ExecMode.LOCAL, on_output)
        Path(script).unlink(missing_ok=True)
        return result.stdout

    async def _local_exec(
        self, code: str, on_output: Optional[Callable[[str], None]] = None,
    ) -> ExecResult:
        """Execute via local spark-submit."""
        if is_pipeline_source(code):
            return await self._local_pipeline_exec(code, on_output)
        try:
            names, jars = await self._connector_jars(code)
        except (OSError, ValueError) as e:
            return self._connector_error(ExecMode.LOCAL, e)
        if names and runs_with_python(code):
            return self._connector_error(ExecMode.LOCAL, ValueError(
                "'# spark-run: python' exercises build their own session; "
                "pass connector jars with spark.jars instead of '# spark-connectors:'"))

        with tempfile.TemporaryDirectory(prefix="sparktutor_") as tmp:
            root = Path(tmp)
            script = write_script_project(code, root)
            if runs_with_python(code):
                launcher = [sys.executable]
            else:
                launcher = [spark_bin("spark-submit"),
                            *connector_args(names, [str(jar) for jar in jars], in_pipeline=False)]
            proc = await asyncio.create_subprocess_exec(
                *launcher,
                str(script),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=spark_env(),
                cwd=str(root),
            )
            return await self._stream_process(proc, ExecMode.LOCAL, on_output)

    async def _databricks_exec(
        self, code: str, on_output: Optional[Callable[[str], None]] = None,
    ) -> ExecResult:
        """Execute via Databricks Spark Connect (python3, not spark-submit)."""
        if is_pipeline_source(code):
            return ExecResult(
                mode=ExecMode.DATABRICKS, exit_code=1, stdout="",
                stderr=(
                    "[sparktutor] Spark Declarative Pipelines exercises run with the "
                    "spark-pipelines CLI. Switch the execution mode to local or lakehouse."
                ),
            )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        env = {**os.environ}
        # Set SPARK_REMOTE if explicit config provides it
        remote_url = self.settings.databricks.build_spark_remote()
        if remote_url:
            env["SPARK_REMOTE"] = remote_url
        # Set profile if configured
        if self.settings.databricks.profile:
            env["DATABRICKS_CONFIG_PROFILE"] = self.settings.databricks.profile

        proc = await asyncio.create_subprocess_exec(
            "python3", tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        result = await self._stream_process(proc, ExecMode.DATABRICKS, on_output)
        Path(tmp_path).unlink(missing_ok=True)
        return result

    async def _stream_process(
        self,
        proc: asyncio.subprocess.Process,
        mode: ExecMode,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> ExecResult:
        """Stream stdout/stderr from a subprocess, calling on_output for each line."""
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        async def _read_stream(
            stream: Optional[asyncio.StreamReader], lines: list[str], is_stderr: bool = False,
        ):
            if stream is None:
                return
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                lines.append(decoded)
                if on_output:
                    prefix = "[stderr] " if is_stderr else ""
                    on_output(f"{prefix}{decoded}")

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _read_stream(proc.stdout, stdout_lines),
                    _read_stream(proc.stderr, stderr_lines, is_stderr=True),
                ),
                timeout=self.settings.timeout_seconds,
            )
            await proc.wait()
        except asyncio.TimeoutError:
            proc.kill()
            stderr_lines.append(f"[sparktutor] Execution timed out after {self.settings.timeout_seconds}s")

        return ExecResult(
            mode=mode,
            exit_code=proc.returncode if proc.returncode is not None else 1,
            stdout="\n".join(stdout_lines),
            stderr="\n".join(stderr_lines),
        )
