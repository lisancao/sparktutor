"""Tests for the executor (dry-run mode only — no Docker needed)."""

import pytest

from sparktutor.engine.executor import ExecMode, ExecResult, Executor


class TestDryRun:
    @pytest.fixture
    def executor(self):
        return Executor(force_dry_run=True)

    def test_dry_run_valid_syntax(self, executor):
        result = executor._dry_run("x = 42\nprint(x)")
        assert result.success
        assert result.mode == ExecMode.DRY_RUN
        assert "Syntax OK" in result.stdout

    def test_dry_run_syntax_error(self, executor):
        result = executor._dry_run("x = ")
        assert not result.success
        assert "SyntaxError" in result.stderr

    def test_dry_run_multiline(self, executor):
        code = """
from pyspark.sql import SparkSession

spark = SparkSession.builder.appName('test').getOrCreate()
df = spark.read.csv('/data/test.csv', header=True)
df.show()
"""
        result = executor._dry_run(code)
        assert result.success


class TestExecResult:
    def test_success(self):
        r = ExecResult(mode=ExecMode.DRY_RUN, exit_code=0, stdout="ok", stderr="")
        assert r.success

    def test_failure(self):
        r = ExecResult(mode=ExecMode.DRY_RUN, exit_code=1, stdout="", stderr="error")
        assert not r.success


@pytest.mark.asyncio
async def test_detect_mode_dry_run():
    executor = Executor(force_dry_run=True)
    mode = await executor.detect_mode()
    assert mode == ExecMode.DRY_RUN


@pytest.mark.asyncio
async def test_execute_dry_run():
    executor = Executor(force_dry_run=True)
    result = await executor.execute("x = 42")
    assert result.success
    assert result.mode == ExecMode.DRY_RUN
