"""Error parsing and line-level diagnostic mapping."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sparktutor.engine.evaluator import FeedbackItem


# Common Spark/Python error patterns → friendly messages
ERROR_PATTERNS: list[tuple[str, str, str]] = [
    # (regex, severity, user-friendly message)
    (r"AnalysisException.*Table or view not found: (\S+)",
     "error", "表 '{0}' 不存在。请检查表名和 catalog 配置。"),
    (r"AnalysisException.*cannot resolve '(\w+)'",
     "error", "找不到列 '{0}'。请用 df.printSchema() 检查列名。"),
    (r"Py4JJavaError.*ClassNotFoundException: (\S+)",
     "error", "缺少依赖：{0}。JAR 包可能不在 classpath 中。"),
    (r"NameError: name '(\w+)' is not defined",
     "error", "变量 '{0}' 未定义。是否忘记导入或创建了？"),
    (r"TypeError: (.+)",
     "error", "类型错误：{0}"),
    (r"AttributeError: '(\w+)' object has no attribute '(\w+)'",
     "error", "'{0}' 没有 '{1}' 属性。请查阅 API 文档。"),
    (r"IndentationError: (.+)",
     "error", "缩进错误：{0}。请检查空白符。"),
    (r"SyntaxError: (.+)",
     "error", "语法错误：{0}"),
    (r"spark\.sql\.shuffle\.partitions",
     "info", "提示：shuffle 分区数默认为 200。对于小数据量可以调低。"),
    (r"WARN.*deprecated",
     "info", "检测到弃用警告 —— 代码仍可运行，但建议更新写法。"),
]


def parse_stderr(stderr: str) -> list[FeedbackItem]:
    """Parse spark-submit stderr into structured feedback items."""
    if not stderr:
        return []

    feedback: list[FeedbackItem] = []
    seen_messages: set[str] = set()

    for pattern, severity, template in ERROR_PATTERNS:
        match = re.search(pattern, stderr, re.IGNORECASE)
        if match:
            groups = match.groups()
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
