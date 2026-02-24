"""Tests for depth-aware scaffolding generation."""

from sparktutor.engine.scaffolding import generate_scaffold


def test_beginner_sparksession_scaffold():
    """Beginner gets import + builder skeleton with TODOs."""
    result = generate_scaffold(
        step_output="Create a SparkSession with the app name 'MyPipeline'.",
        step_cls="cmd_question",
        depth="beginner",
        correct_answer=(
            "from pyspark.sql import SparkSession\n"
            "spark = SparkSession.builder.appName('MyPipeline').getOrCreate()"
        ),
    )
    assert "from pyspark.sql import SparkSession" in result
    assert "TODO" in result
    assert "SparkSession.builder" in result
    # Should NOT contain the literal answer
    assert "appName('MyPipeline')" not in result


def test_intermediate_shows_concepts_not_code():
    """Intermediate gets concept hints, not boilerplate."""
    result = generate_scaffold(
        step_output="Create a SparkSession named 'PipelineApp' with shuffle partitions set to 8.",
        step_cls="cmd_question",
        depth="intermediate",
        correct_answer=(
            "from pyspark.sql import SparkSession\n"
            "spark = (SparkSession.builder\n"
            "    .appName('PipelineApp')\n"
            "    .config('spark.sql.shuffle.partitions', '8')\n"
            "    .getOrCreate())"
        ),
    )
    # Should mention key APIs
    assert "SparkSession.builder" in result
    assert ".config(" in result or "config" in result.lower()
    # Should NOT contain full skeleton
    assert "TODO" not in result
    assert "pass" not in result


def test_advanced_minimal():
    """Advanced gets just the objective as a comment."""
    result = generate_scaffold(
        step_output="Create a SparkSession with an Iceberg catalog named 'lakehouse'.",
        step_cls="cmd_question",
        depth="advanced",
        correct_answer="from pyspark.sql import SparkSession\nspark = ...",
    )
    # Should be very short
    lines = [l for l in result.strip().splitlines() if l.strip()]
    assert len(lines) <= 2
    assert result.startswith("#")
    assert "TODO" not in result


def test_text_steps_get_no_scaffold():
    """Text steps should not produce any scaffold."""
    result = generate_scaffold(
        step_output="Welcome to the lesson.",
        step_cls="text",
        depth="beginner",
    )
    assert result == ""


def test_mult_question_no_scaffold():
    """Multiple choice steps should not produce scaffold."""
    result = generate_scaffold(
        step_output="Which method creates a SparkSession?",
        step_cls="mult_question",
        depth="beginner",
    )
    assert result == ""


def test_beginner_function_scaffold():
    """Beginner gets function stub when answer defines a function."""
    result = generate_scaffold(
        step_output="Write a function called bronze_orders that reads from Kafka.",
        step_cls="cmd_question",
        depth="beginner",
        correct_answer=(
            "from pyspark.sql import SparkSession\n"
            "def bronze_orders(spark):\n"
            "    return spark.readStream.format('kafka').load()\n"
        ),
    )
    assert "def bronze_orders" in result
    assert "TODO" in result


def test_intermediate_function_concepts():
    """Intermediate gets concept list for function-based answer."""
    result = generate_scaffold(
        step_output="Write a function called bronze_orders that reads from Kafka.",
        step_cls="cmd_question",
        depth="intermediate",
        correct_answer=(
            "def bronze_orders(spark):\n"
            "    return spark.readStream.format('kafka').load()\n"
        ),
    )
    assert "bronze_orders" in result or "readStream" in result


def test_empty_correct_answer_still_produces_scaffold():
    """Even without a correct answer, beginner gets generic scaffold."""
    result = generate_scaffold(
        step_output="Write code to read a CSV file.",
        step_cls="cmd_question",
        depth="beginner",
        correct_answer="",
        hint="Use spark.read.csv(path)",
    )
    assert "TODO" in result or "Hint" in result
