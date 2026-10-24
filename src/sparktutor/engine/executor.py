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
    df = spark.read.parquet(str(path))
    print(f"\\n=== {name} ({df.count()} rows) ===")
    df.show(10, truncate=False)
spark.stop()
"""


def write_pipeline_project(code: str, root: Path, storage_root: str | None = None) -> Path:
    """Lay out a one-file pipeline project under root and return its spec path.

    The sample dataset is copied to root/data so exercises can read it with
    relative paths; spark-pipelines runs with root as its working directory.
    """
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
    )
    return spec


def pipeline_command(code: str) -> str:
    """The spark-pipelines subcommand an exercise asks for."""
    return "dry-run" if _SDP_DRY_RUN.search(code) else "run"


def spark_bin(name: str) -> str:
    """Find a Spark launcher, preferring the one installed next to this interpreter."""
    candidate = Path(sys.executable).parent / name
    if candidate.exists():
        return str(candidate)
    return shutil.which(name) or name


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

    def _dry_run(self, code: str) -> ExecResult:
        """Syntax check only — no Spark execution."""
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

        # Write code to a unique temp file to avoid collisions
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", prefix="sparktutor_", delete=False) as tmp:
            tmp.write(code)
            tmp_path = tmp.name
        remote_path = f"/tmp/{Path(tmp_path).name}"

        # docker cp
        cp_proc = await asyncio.create_subprocess_exec(
            "docker", "cp", tmp_path, f"{container}:{remote_path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await cp_proc.communicate()
        Path(tmp_path).unlink(missing_ok=True)

        # docker exec spark-submit (no --jars flag!)
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container,
            "/opt/spark/bin/spark-submit",
            "--master", self.settings.docker.spark_master_url,
            remote_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        return await self._stream_process(proc, ExecMode.LAKEHOUSE, on_output)

    async def _lakehouse_pipeline_exec(
        self, code: str, on_output: Optional[Callable[[str], None]] = None,
    ) -> ExecResult:
        """Run a pipeline definitions file with spark-pipelines inside the container."""
        container = self.settings.docker.container_name
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
            "/opt/spark/bin/spark-pipelines", pipeline_command(code),
            "--spec", f"{remote_root}/spark-pipeline.yml",
            "--master", self.settings.docker.spark_master_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return await self._stream_process(proc, ExecMode.LAKEHOUSE, on_output)

    async def _local_pipeline_exec(
        self, code: str, on_output: Optional[Callable[[str], None]] = None,
    ) -> ExecResult:
        """Run a pipeline definitions file with a local spark-pipelines."""
        with tempfile.TemporaryDirectory(prefix="sparktutor_sdp_") as tmp:
            root = Path(tmp)
            spec = write_pipeline_project(code, root)
            command = pipeline_command(code)
            proc = await asyncio.create_subprocess_exec(
                spark_bin("spark-pipelines"), command, "--spec", str(spec),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(root),
            )
            result = await self._stream_process(proc, ExecMode.LOCAL, on_output)
            if result.success and command == "run":
                preview = await self._preview_tables(root / "spark-warehouse", on_output)
                result.stdout = "\n".join(filter(None, [result.stdout, preview]))
            return result

    async def _preview_tables(
        self, warehouse: Path, on_output: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Show the contents of the tables a pipeline run wrote."""
        if not warehouse.is_dir():
            return ""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
            tmp.write(_PREVIEW_SCRIPT)
            script = tmp.name
        proc = await asyncio.create_subprocess_exec(
            spark_bin("spark-submit"), script, str(warehouse),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        proc = await asyncio.create_subprocess_exec(
            spark_bin("spark-submit"), tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        result = await self._stream_process(proc, ExecMode.LOCAL, on_output)
        Path(tmp_path).unlink(missing_ok=True)
        return result

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
