"""Tests for the executor (dry-run mode only — no Docker needed)."""

import pytest

from sparktutor.config.settings import DatabricksConfig, ExecutionMode, Settings
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


class TestDatabricksConfig:
    def test_build_spark_remote_full(self):
        cfg = DatabricksConfig(
            host="adb-123.45.azuredatabricks.net",
            token="dapi_abc123",
            cluster_id="0101-abcdef",
        )
        url = cfg.build_spark_remote()
        assert url == (
            "sc://adb-123.45.azuredatabricks.net:443/"
            ";use_ssl=true;token=dapi_abc123"
            ";x-databricks-cluster-id=0101-abcdef"
        )

    def test_build_spark_remote_strips_trailing_slash(self):
        cfg = DatabricksConfig(
            host="adb-123.45.azuredatabricks.net/",
            token="tok",
            cluster_id="cid",
        )
        assert cfg.build_spark_remote().startswith("sc://adb-123.45.azuredatabricks.net:443/")

    def test_build_spark_remote_missing_fields(self):
        assert DatabricksConfig().build_spark_remote() is None
        assert DatabricksConfig(host="h").build_spark_remote() is None
        assert DatabricksConfig(host="h", token="t").build_spark_remote() is None

    def test_build_spark_remote_profile_only(self):
        cfg = DatabricksConfig(profile="STAGING")
        assert cfg.build_spark_remote() is None


@pytest.mark.asyncio
async def test_detect_mode_databricks():
    settings = Settings(execution_mode=ExecutionMode.DATABRICKS)
    executor = Executor(settings=settings)
    mode = await executor.detect_mode()
    assert mode == ExecMode.DATABRICKS


class TestExecResultDatabricks:
    def test_databricks_mode(self):
        r = ExecResult(mode=ExecMode.DATABRICKS, exit_code=0, stdout="ok", stderr="")
        assert r.success
        assert r.mode == ExecMode.DATABRICKS
