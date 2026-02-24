"""Spark code execution engine with three-mode graceful degradation."""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from sparktutor.config.settings import Settings


class ExecMode(str, Enum):
    LAKEHOUSE = "lakehouse"
    LOCAL = "local"
    DRY_RUN = "dry_run"


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

        # Check for local spark-submit
        try:
            proc = await asyncio.create_subprocess_exec(
                "spark-submit", "--version",
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
        """Execute via docker exec on spark-master-41."""
        container = self.settings.docker.container_name

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

    async def _local_exec(
        self, code: str, on_output: Optional[Callable[[str], None]] = None,
    ) -> ExecResult:
        """Execute via local spark-submit."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        proc = await asyncio.create_subprocess_exec(
            "spark-submit", tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        result = await self._stream_process(proc, ExecMode.LOCAL, on_output)
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
            exit_code=proc.returncode or 1,
            stdout="\n".join(stdout_lines),
            stderr="\n".join(stderr_lines),
        )
