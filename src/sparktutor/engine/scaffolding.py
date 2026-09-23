"""Depth-aware code scaffolding for exercise steps.

Generates starter code calibrated to the student's level:
- Beginner: full skeleton with TODOs, comments showing structure, import hints
- Intermediate: structural hints (where things go, what options exist)
- Advanced: minimal — just the objective as a comment
"""

from __future__ import annotations

import re
def generate_scaffold(
    step_output: str,
    step_cls: str,
    depth: str,
    correct_answer: str = "",
    hint: str = "",
    lesson_title: str = "",  # noqa: ARG001 — reserved for future use
) -> str:
    """Generate depth-appropriate starter code for a step.

    Args:
        step_output: The step's instruction text (what the user is asked to do).
        step_cls: Step class — "cmd_question", "script", etc.
        depth: "beginner", "intermediate", or "advanced".
        correct_answer: The solution (used to extract structure, never shown directly).
        hint: The step's hint text.
        lesson_title: Current lesson title for context.

    Returns:
        Scaffold code string, or empty string if no scaffold is appropriate.
    """
    if step_cls not in ("cmd_question", "script"):
        return ""

    if depth == "beginner":
        return _beginner_scaffold(step_output, correct_answer, hint)
    elif depth == "intermediate":
        return _intermediate_scaffold(step_output, correct_answer, hint)
    else:
        return _advanced_scaffold(step_output)


def _beginner_scaffold(
    step_output: str, correct_answer: str, hint: str
) -> str:
    """Beginner: boilerplate skeleton with TODOs and structural comments.

    Extracts imports and structure from the correct answer without revealing
    the logic. Shows the student WHERE things go and WHAT to use.
    """
    lines: list[str] = []

    # Extract imports from the correct answer (safe to show — they're not the logic)
    imports = _extract_imports(correct_answer)
    if imports:
        for imp in imports:
            lines.append(imp)
        lines.append("")

    # Extract structural hints from the correct answer
    structure = _extract_structure(correct_answer)

    if structure.get("builder_pattern"):
        # SparkSession builder pattern
        lines.append("# TODO: 使用建造者模式创建 SparkSession")
        lines.append("# 提示: SparkSession.builder.appName(...)")
        lines.append("spark = (SparkSession.builder")
        lines.append("    # TODO: 设置应用名称和配置")
        lines.append("    # .appName('...')")
        lines.append("    # .config('key', 'value')")
        lines.append("    .getOrCreate())")
    elif structure.get("has_function_def"):
        # Function definition scaffolding
        for func_name, func_args in structure["functions"]:
            lines.append(f"def {func_name}({', '.join(func_args)}):")
            lines.append(f"    # TODO: 实现 {func_name}")
            lines.append("    pass")
            lines.append("")
    elif structure.get("has_class_def"):
        # Class definition scaffolding
        for cls_name, methods in structure["classes"]:
            lines.append(f"class {cls_name}:")
            for method_name, method_args in methods:
                args_str = ", ".join(method_args) if method_args else "self"
                lines.append(f"    def {method_name}({args_str}):")
                lines.append(f"        # TODO: 实现 {method_name}")
                lines.append("        pass")
                lines.append("")
    else:
        # Generic scaffolding — use the hint
        lines.append(f"# 练习：{_first_sentence(step_output)}")
        if hint:
            lines.append(f"# 提示：{hint}")
        lines.append("")
        lines.append("# TODO: 在下方编写代码")
        lines.append("")

    return "\n".join(lines) + "\n"


def _intermediate_scaffold(
    step_output: str, correct_answer: str, hint: str  # noqa: ARG001
) -> str:
    """Intermediate: structural hints about where things go and what's available.

    No boilerplate — just comments indicating the shape of the solution.
    """
    lines: list[str] = []
    lines.append(f"# {_first_sentence(step_output)}")

    # Extract key concepts the student needs to use
    concepts = _extract_key_concepts(correct_answer)
    if concepts:
        lines.append("#")
        lines.append("# 需要使用的关键 API/概念：")
        for concept in concepts:
            lines.append(f"#   - {concept}")

    lines.append("")
    return "\n".join(lines) + "\n"


def _advanced_scaffold(step_output: str) -> str:
    """Advanced: just the objective, no hints."""
    return f"# {_first_sentence(step_output)}\n"


# --- Extraction helpers ---


def _extract_imports(code: str) -> list[str]:
    """Extract import lines from code (safe to reveal — they indicate what library to use)."""
    if not code.strip():
        return []
    imports = []
    for line in code.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            imports.append(stripped)
    return imports


def _extract_structure(code: str) -> dict:
    """Analyze code structure without revealing the logic."""
    import ast

    result: dict = {
        "builder_pattern": False,
        "has_function_def": False,
        "has_class_def": False,
        "functions": [],
        "classes": [],
    }

    if not code.strip():
        return result

    # Check for SparkSession builder pattern
    if "SparkSession.builder" in code:
        result["builder_pattern"] = True

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return result

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            result["has_function_def"] = True
            args = [arg.arg for arg in node.args.args]
            result["functions"].append((node.name, args))
        elif isinstance(node, ast.ClassDef):
            result["has_class_def"] = True
            methods = []
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    args = [arg.arg for arg in item.args.args]
                    methods.append((item.name, args))
            result["classes"].append((node.name, methods))

    return result


def _extract_key_concepts(code: str) -> list[str]:
    """Extract the key API calls and patterns from the correct answer.

    Returns human-readable concept descriptions, not the literal code.
    """
    if not code.strip():
        return []

    concepts = []

    # Detect common patterns
    if "SparkSession.builder" in code:
        concepts.append("SparkSession.builder（建造者模式）")
    if ".appName(" in code:
        concepts.append(".appName() — 设置应用名称")
    if ".config(" in code:
        configs = re.findall(r"\.config\(['\"]([^'\"]+)['\"]", code)
        for cfg in configs:
            concepts.append(f".config('{cfg}', ...) — 配置项")
    if ".getOrCreate()" in code:
        concepts.append(".getOrCreate() — 创建或复用会话")
    if "spark.read" in code:
        concepts.append("spark.read — 批量数据读取器")
    if "spark.readStream" in code:
        concepts.append("spark.readStream — 流式读取器")
    if ".write." in code or ".save(" in code:
        concepts.append("DataFrame.write — 输出写入器")
    if ".groupBy(" in code:
        concepts.append(".groupBy() — 分组聚合")
    if ".join(" in code:
        concepts.append(".join() — 合并 DataFrame")
    if ".filter(" in code or ".where(" in code:
        concepts.append(".filter() / .where() — 行过滤")
    if ".withColumn(" in code:
        concepts.append(".withColumn() — 添加/替换列")
    if "createDataFrame" in code:
        concepts.append("spark.createDataFrame() — 从本地数据创建")
    if "class " in code:
        class_names = re.findall(r"class\s+(\w+)", code)
        for name in class_names:
            concepts.append(f"class {name} — 定义类")
    if "def " in code and "class " not in code:
        func_names = re.findall(r"def\s+(\w+)", code)
        for name in func_names:
            if name != "__init__":
                concepts.append(f"def {name}() — 定义函数")

    return concepts


def _first_sentence(text: str) -> str:
    """Extract the first sentence or line from markdown text."""
    # Strip markdown formatting
    clean = text.strip()
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", clean)
    clean = re.sub(r"`(.+?)`", r"\1", clean)

    # Take first sentence
    for sep in [".\n", ".\r", ". "]:
        idx = clean.find(sep)
        if idx > 0:
            return clean[: idx + 1]

    # Take first line
    first_line = clean.split("\n")[0].strip()
    return first_line[:120]
