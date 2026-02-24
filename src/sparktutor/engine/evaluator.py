"""Two-layer evaluation engine: local AST checks + Claude API review."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Optional

from sparktutor.config.settings import Settings
from sparktutor.engine.normalizer import choices_match, code_match


@dataclass
class FeedbackItem:
    line: Optional[int]
    severity: str  # "error", "warning", "info", "success"
    message: str
    suggestion: Optional[str] = None


@dataclass
class EvalResult:
    passed: bool
    feedback: list[FeedbackItem] = field(default_factory=list)
    encouragement: str = ""
    skill_signals: list[str] = field(default_factory=list)


class Evaluator:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings.load()
        self._client = None

    def _get_client(self):
        if self._client is None:
            api_key = self.settings.claude.get_api_key()
            if api_key:
                import anthropic
                self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    # --- Layer 1: Local checks (instant) ---

    def check_syntax(self, code: str) -> EvalResult:
        """Parse code and return syntax errors."""
        try:
            ast.parse(code)
            return EvalResult(passed=True)
        except SyntaxError as e:
            return EvalResult(
                passed=False,
                feedback=[FeedbackItem(
                    line=e.lineno,
                    severity="error",
                    message=f"SyntaxError: {e.msg}",
                    suggestion=None,
                )],
            )

    def check_mult_choice(self, guess: str, correct: str) -> EvalResult:
        """Evaluate a multiple-choice answer."""
        if choices_match(guess, correct):
            return EvalResult(passed=True, encouragement="Correct!")
        return EvalResult(
            passed=False,
            feedback=[FeedbackItem(
                line=None, severity="warning",
                message=f"Not quite. The correct answer is: {correct}",
            )],
        )

    def check_code_exact(self, guess: str, correct: str) -> EvalResult:
        """Exact code match (with normalization)."""
        if code_match(guess, correct):
            return EvalResult(passed=True, encouragement="Well done!")
        return EvalResult(passed=False)

    def check_ast_contains(self, code: str, checks: list[dict]) -> EvalResult:
        """Check that code AST contains required elements."""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return EvalResult(
                passed=False,
                feedback=[FeedbackItem(line=e.lineno, severity="error", message=f"SyntaxError: {e.msg}")],
            )

        feedback: list[FeedbackItem] = []
        all_passed = True

        for check in checks:
            expr = check.get("expr", "")

            # Parse ast_contains(class_def='Pipeline')
            m = re.match(r"ast_contains\((.+)\)", expr)
            if not m:
                continue

            params_str = m.group(1)
            # Parse key=value pairs
            for param in params_str.split(","):
                param = param.strip()
                key, _, value = param.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")

                found = False
                if key == "class_def":
                    found = any(
                        isinstance(node, ast.ClassDef) and node.name == value
                        for node in ast.walk(tree)
                    )
                elif key == "method":
                    found = any(
                        isinstance(node, ast.FunctionDef) and node.name == value
                        for node in ast.walk(tree)
                    )
                elif key == "function":
                    found = any(
                        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == value
                        for node in ast.walk(tree)
                    )
                elif key == "args":
                    # Check if any function has the specified args
                    import ast as _ast
                    target_args = [a.strip().strip("'\"") for a in value.strip("[]").split(",")]
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            func_args = [arg.arg for arg in node.args.args]
                            if func_args == target_args:
                                found = True
                                break
                elif key == "import":
                    found = any(
                        (isinstance(node, ast.Import) and any(a.name == value for a in node.names))
                        or (isinstance(node, ast.ImportFrom) and node.module and value in node.module)
                        for node in ast.walk(tree)
                    )
                elif key == "call":
                    found = any(
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == value
                        for node in ast.walk(tree)
                    )

                if not found:
                    all_passed = False
                    feedback.append(FeedbackItem(
                        line=None, severity="warning",
                        message=f"Missing required element: {key}='{value}'",
                        suggestion=f"Make sure your code includes a {key} named '{value}'",
                    ))

        return EvalResult(passed=all_passed, feedback=feedback)

    # --- Layer 2: Claude API review (1-3s) ---

    async def claude_review(
        self,
        code: str,
        lesson_title: str,
        objective: str,
        depth: str,
        stdout: str = "",
        stderr: str = "",
        solution_hint: str = "",
    ) -> EvalResult:
        """Use Claude API for deep code review and adaptive feedback."""
        client = self._get_client()
        if client is None:
            return EvalResult(
                passed=False,
                feedback=[FeedbackItem(
                    line=None, severity="info",
                    message="Claude API not configured — using local checks only.",
                )],
            )

        prompt = f"""You are a Spark tutor evaluating a student's PySpark code for a lesson on "{lesson_title}".

Student depth level: {depth}
Lesson objective: {objective}
{f'Solution approach hint: {solution_hint}' if solution_hint else ''}

Student code:
```python
{code}
```

{f'Execution stdout:\\n{stdout}' if stdout else 'No execution output.'}
{f'Execution stderr:\\n{stderr}' if stderr else ''}

Respond in JSON:
{{
  "passed": true/false,
  "feedback": [
    {{"line": <int or null>, "severity": "error|warning|info", "message": "<text>", "suggestion": "<fix or null>"}}
  ],
  "encouragement": "<one sentence calibrated to their depth level>",
  "skill_signals": ["<observed competency or gap>"]
}}

Calibrate feedback to the student's level:
- beginner: be encouraging, explain concepts, give concrete examples
- intermediate: be specific about patterns, mention alternatives
- advanced: challenge on performance, edge cases, production readiness"""

        try:
            response = client.messages.create(
                model=self.settings.claude.get_model(),
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            # Extract JSON from response
            json_match = re.search(r"\{[\s\S]*\}", text)
            if json_match:
                data = json.loads(json_match.group())
                return EvalResult(
                    passed=data.get("passed", False),
                    feedback=[
                        FeedbackItem(
                            line=f.get("line"),
                            severity=f.get("severity", "info"),
                            message=f.get("message", ""),
                            suggestion=f.get("suggestion"),
                        )
                        for f in data.get("feedback", [])
                    ],
                    encouragement=data.get("encouragement", ""),
                    skill_signals=data.get("skill_signals", []),
                )
        except Exception as e:
            return EvalResult(
                passed=False,
                feedback=[FeedbackItem(
                    line=None, severity="warning",
                    message=f"Claude review failed: {e}",
                )],
            )

        return EvalResult(passed=False)

    # --- Composite evaluation ---

    async def evaluate(
        self,
        code: str,
        step,  # Step dataclass
        depth: str = "beginner",
        exec_result=None,  # ExecResult
        lesson_title: str = "",
    ) -> EvalResult:
        """Run the appropriate evaluation for a step."""
        # Multiple choice
        if step.cls == "mult_question" and step.correct_answer:
            return self.check_mult_choice(code, step.correct_answer)

        # Code questions: try local checks first
        syntax = self.check_syntax(code)
        if not syntax.passed:
            return syntax

        # Exact match check
        if step.correct_answer:
            exact = self.check_code_exact(code, step.correct_answer)
            if exact.passed:
                return EvalResult(passed=True, encouragement="Correct!")

        # AST structural checks
        ast_checks = [v.params for v in step.validation if v.type == "ast_contains"]
        if ast_checks:
            ast_result = self.check_ast_contains(code, ast_checks)
            if not ast_result.passed:
                return ast_result

        # Claude review for script steps or when local checks are insufficient
        has_claude_review = any(v.type == "claude_review" for v in step.validation)
        if has_claude_review or (step.cls == "script" and not step.correct_answer):
            criteria = ""
            for v in step.validation:
                if v.type == "claude_review":
                    criteria = v.params.get("criteria", "")
                    break
            return await self.claude_review(
                code=code,
                lesson_title=lesson_title,
                objective=criteria or step.output,
                depth=depth,
                stdout=exec_result.stdout if exec_result else "",
                stderr=exec_result.stderr if exec_result else "",
            )

        # If we got past exact match without passing, do Claude review as fallback
        if step.correct_answer:
            return await self.claude_review(
                code=code,
                lesson_title=lesson_title,
                objective=step.output,
                depth=depth,
                stdout=exec_result.stdout if exec_result else "",
                stderr=exec_result.stderr if exec_result else "",
                solution_hint=step.correct_answer,
            )

        # No validation rules — pass if syntax is OK
        return EvalResult(passed=True, encouragement="Code looks good!")

    # --- Chat: freeform Q&A ---

    async def chat(
        self,
        question: str,
        lesson_title: str = "",
        step_context: str = "",
        code_context: str = "",
        depth: str = "beginner",
    ) -> str:
        """Answer a freeform question about the current lesson/code using Claude."""
        client = self._get_client()
        if client is None:
            return "Claude API not configured. Set ANTHROPIC_API_KEY to enable chat."

        prompt = f"""You are SparkTutor, an interactive Apache Spark 4.1 tutor embedded in a terminal learning app.

The student is working on: "{lesson_title}"
Current exercise: {step_context}
Student depth level: {depth}

{f'Their current code:\\n```python\\n{code_context}\\n```' if code_context else ''}

Student question: {question}

Answer concisely (2-4 sentences). Be direct and helpful. If the question is about their code, reference specific lines. Calibrate your explanation to their depth level. Use markdown for code snippets."""

        try:
            response = client.messages.create(
                model=self.settings.claude.get_model(),
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            return f"Chat error: {e}"
