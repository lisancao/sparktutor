"""Error parsing and line-level diagnostic mapping."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sparktutor.engine.evaluator import FeedbackItem


# Common Spark/Python error patterns → friendly messages
ERROR_PATTERNS: list[tuple[str, str, str]] = [
    # (regex, severity, user-friendly message)
    # Spark 4 reports errors by error class, e.g. [TABLE_OR_VIEW_NOT_FOUND] ... SQLSTATE: 42P01
    (r"\[USER_RAISED_EXCEPTION\] (.+?)(?: SQLSTATE: \w+)?$",
     "error", "Check failed: {0}"),
    (r"\[TABLE_OR_VIEW_NOT_FOUND\] The table or view (\S+) cannot be found",
     "error", "Table '{0}' doesn't exist. Check the name, and in a pipeline make sure a dataset with that name is defined."),
    (r"\[UNRESOLVED_COLUMN\.\w+\] A column, variable, or function parameter with name (\S+) cannot be resolved",
     "error", "Column '{0}' not found. Check your column names with df.printSchema()."),
    (r"\[CAST_INVALID_INPUT\] The value '([^']*)'",
     "error", "ANSI mode rejected casting '{0}'. Use try_cast(...) to turn malformed values into NULL."),
    (r"\[DIVIDE_BY_ZERO\]",
     "error", "Division by zero under ANSI mode. Use try_divide(...) or guard the denominator."),
    (r"\[GRAPH_ELEMENT_DEFINED_OUTSIDE_OF_DECLARATIVE_PIPELINE\]",
     "error", "Pipeline decorators only work inside a pipeline run. Run this file with spark-pipelines, not spark-submit."),
    (r"\[AUTOCDC_TARGET_DOES_NOT_SUPPORT_MERGE\]",
     "error", "Auto CDC needs a target table format that supports MERGE (for example Iceberg). Parquet and Delta targets are rejected."),
    (r"\[(AUTOCDC_[A-Z_]+)\] (.+?)(?: SQLSTATE: \w+)?$",
     "error", "Auto CDC error {0}: {1}"),
    (r"\[(PIPELINE_[A-Z_]+)\] (.+?)(?: SQLSTATE: \w+)?$",
     "error", "Pipeline error {0}: {1}"),
    (r"AnalysisException.*Table or view not found: (\S+)",
     "error", "Table '{0}' doesn't exist. Check the table name and catalog."),
    (r"Py4JJavaError.*ClassNotFoundException: (\S+)",
     "error", "Missing dependency: {0}. The JAR may not be on the classpath."),
    (r"NameError: name '(\w+)' is not defined",
     "error", "Variable '{0}' is not defined. Did you forget to import or create it?"),
    (r"TypeError: (.+)",
     "error", "Type error: {0}"),
    (r"AttributeError: '(\w+)' object has no attribute '(\w+)'",
     "error", "'{0}' doesn't have attribute '{1}'. Check the API docs."),
    (r"IndentationError: (.+)",
     "error", "Indentation error: {0}. Check your whitespace."),
    (r"SyntaxError: (.+)",
     "error", "Syntax error: {0}"),
    (r"spark\.sql\.shuffle\.partitions",
     "info", "Tip: shuffle partitions defaults to 200. For small data, set it lower."),
    (r"WARN.*deprecated",
     "info", "Deprecation warning detected; the code still works but consider updating."),
]


def parse_stderr(stderr: str) -> list[FeedbackItem]:
    """Parse spark-submit stderr into structured feedback items."""
    if not stderr:
        return []

    feedback: list[FeedbackItem] = []
    seen_messages: set[str] = set()

    for pattern, severity, template in ERROR_PATTERNS:
        match = re.search(pattern, stderr, re.IGNORECASE | re.MULTILINE)
        if match:
            groups = tuple(g.replace("`", "") for g in match.groups())
            message = template.format(*groups) if groups else template
            if message not in seen_messages:
                seen_messages.add(message)
                feedback.append(FeedbackItem(
                    line=_extract_line_number(stderr, match.start()),
                    severity=severity,
                    message=message,
                ))

    # If no patterns matched but there's an error, extract the last exception
    if not feedback and "Error" in stderr:
        last_error = _extract_last_error(stderr)
        if last_error:
            feedback.append(FeedbackItem(
                line=None, severity="error", message=last_error,
            ))

    return feedback


def _extract_line_number(stderr: str, match_pos: int) -> int | None:
    """Try to extract a line number from nearby context."""
    # Look for "line N" near the match
    context = stderr[max(0, match_pos - 200) : match_pos + 200]
    m = re.search(r"line (\d+)", context)
    if m:
        return int(m.group(1))
    return None


def _extract_last_error(stderr: str) -> str | None:
    """Extract the last meaningful error line from stderr."""
    lines = stderr.strip().split("\n")
    for line in reversed(lines):
        line = line.strip()
        if line and not line.startswith(("WARN", "INFO", "DEBUG", "\t")):
            # Truncate very long lines
            return line[:200] if len(line) > 200 else line
    return None
