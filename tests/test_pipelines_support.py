"""Tests for Spark Declarative Pipelines support in the executor and evaluator."""

import asyncio
import sys

import pytest

from sparktutor.engine.evaluator import Evaluator
from sparktutor.engine.executor import (
    CONNECTORS,
    ExecMode,
    ExecResult,
    Executor,
    connector_args,
    fetch_jars,
    is_pipeline_source,
    pipeline_command,
    requested_connectors,
    spark_env,
    write_pipeline_project,
    write_script_project,
)
from sparktutor.engine.feedback import parse_stderr
from sparktutor.engine.lesson_loader import Step, ValidationRule


SDP_CODE = """from pyspark import pipelines as dp

@dp.materialized_view
def products():
    return spark.range(3)
"""


class TestPipelineDetection:
    @pytest.mark.parametrize("line", [
        "from pyspark import pipelines as dp",
        "import pyspark.pipelines as dp",
        "from pyspark.pipelines import materialized_view",
    ])
    def test_detects_pipeline_imports(self, line):
        assert is_pipeline_source(f"{line}\n")

    def test_plain_pyspark_is_not_a_pipeline(self):
        assert not is_pipeline_source("from pyspark.sql import SparkSession\n")

    def test_dry_run_directive(self):
        assert pipeline_command("# spark-pipelines: dry-run\n" + SDP_CODE) == "dry-run"
        assert pipeline_command(SDP_CODE) == "run"


class TestPipelineProject:
    def test_layout(self, tmp_path):
        spec = write_pipeline_project(SDP_CODE, tmp_path)
        assert spec == tmp_path / "spark-pipeline.yml"
        assert (tmp_path / "transformations" / "exercise.py").read_text() == SDP_CODE
        text = spec.read_text()
        assert "include: transformations/**" in text
        assert f"storage: file://{tmp_path}/storage" in text
        assert "spark.sql.pipelines.maxFlowRetryAttempts" in text

    def test_sample_data_is_copied(self, tmp_path):
        write_pipeline_project(SDP_CODE, tmp_path)
        assert (tmp_path / "data" / "customers.csv").exists()
        assert any((tmp_path / "data" / "orders").glob("*.json"))

    def test_custom_storage_root(self, tmp_path):
        spec = write_pipeline_project(SDP_CODE, tmp_path, storage_root="file:///tmp/remote/storage")
        assert "storage: file:///tmp/remote/storage" in spec.read_text()


class TestScriptProject:
    def test_script_and_data(self, tmp_path):
        script = write_script_project("print(1)\n", tmp_path)
        assert script == tmp_path / "exercise.py"
        assert script.read_text() == "print(1)\n"
        assert (tmp_path / "data" / "messy" / "logs" / "access.log").is_file()


class TestConnectors:
    def test_directive_parsing(self):
        code = "# spark-connectors: delta, kafka\n# spark-connectors: delta test-catalog\nx = 1\n"
        assert requested_connectors(code) == ["delta", "kafka", "test-catalog"]

    def test_no_directive(self):
        assert requested_connectors(SDP_CODE) == []

    def test_args_use_jars_not_packages(self):
        args = connector_args(["delta"], ["/j/a.jar", "/j/b.jar"], in_pipeline=False)
        assert args[:2] == ["--jars", "/j/a.jar,/j/b.jar"]
        assert "--packages" not in args
        assert "spark.sql.extensions=io.delta.sql.DeltaSparkSessionExtension" in args

    def test_session_conf_goes_to_spec_for_pipelines(self, tmp_path):
        code = "# spark-connectors: test-catalog\n" + SDP_CODE
        assert "--conf" not in connector_args(["test-catalog"], ["/j/t.jar"], in_pipeline=True)
        assert any("spark.sql.catalog.mem=" in a
                   for a in connector_args(["test-catalog"], ["/j/t.jar"], in_pipeline=False))
        spec = write_pipeline_project(code, tmp_path).read_text()
        assert "spark.sql.catalog.mem:" in spec

    def test_fetch_uses_cache(self, tmp_path):
        for maven_path in CONNECTORS["kafka"].jars:
            (tmp_path / maven_path.rsplit("/", 1)[1]).write_text("cached")
        jars = fetch_jars(["kafka"], tmp_path)
        assert len(jars) == len(CONNECTORS["kafka"].jars)
        assert all(j.read_text() == "cached" for j in jars)

    def test_unknown_connector(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown connector 'iceberg'"):
            fetch_jars(["iceberg"], tmp_path)

    def test_launchers_use_this_interpreter(self, monkeypatch):
        monkeypatch.delenv("PYSPARK_PYTHON", raising=False)
        assert spark_env()["PYSPARK_PYTHON"] == sys.executable


class TestExecutionValidation:
    def _step(self):
        return Step(cls="script", validation=[ValidationRule(type="execution")], requires_execution=True)

    def test_passes_when_run_succeeds(self):
        ok = ExecResult(mode=ExecMode.LOCAL, exit_code=0, stdout="Run is COMPLETED.", stderr="")
        result, needs_ai, _ = asyncio.run(Evaluator().evaluate_local("x = 1", self._step(), exec_result=ok))
        assert result.passed
        assert not needs_ai

    def test_reports_failed_check(self):
        failed = ExecResult(
            mode=ExecMode.LOCAL, exit_code=1, stdout="",
            stderr="Error: [USER_RAISED_EXCEPTION] silver_orders: expected 7 rows, got 5 SQLSTATE: P0001",
        )
        result, needs_ai, _ = asyncio.run(Evaluator().evaluate_local("x = 1", self._step(), exec_result=failed))
        assert not result.passed
        assert not needs_ai
        assert result.feedback[0].message == "Check failed: silver_orders: expected 7 rows, got 5"

    def test_fails_when_not_executed(self):
        result, _, _ = asyncio.run(Evaluator().evaluate_local("x = 1", self._step(), exec_result=None))
        assert not result.passed


class TestSpark4ErrorPatterns:
    def test_table_not_found(self):
        msgs = [f.message for f in parse_stderr(
            "Error: [TABLE_OR_VIEW_NOT_FOUND] The table or view `spark_catalog`.`default`.`orders_bronz` "
            "cannot be found. Verify the spelling"
        )]
        assert any("spark_catalog.default.orders_bronz" in m for m in msgs)

    def test_unresolved_column(self):
        msgs = [f.message for f in parse_stderr(
            "[UNRESOLVED_COLUMN.WITH_SUGGESTION] A column, variable, or function parameter with name "
            "`region` cannot be resolved. Did you mean"
        )]
        assert "Column 'region' not found." in msgs[0]

    def test_ansi_cast(self):
        msgs = [f.message for f in parse_stderr("[CAST_INVALID_INPUT] The value 'N/A' of the type")]
        assert "try_cast" in msgs[0]


@pytest.mark.asyncio
async def test_successful_process_reports_exit_code_zero():
    """Regression: exit code 0 used to be reported as 1 (`returncode or 1`)."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "print('ok')",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    result = await Executor(force_dry_run=True)._stream_process(proc, ExecMode.LOCAL)
    assert result.exit_code == 0
    assert result.success
