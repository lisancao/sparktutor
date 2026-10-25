"""Run every lesson's solution.py against the local Spark install.

Usage: python scripts/verify_solutions.py [course_id[/lesson_id] ...]

Solutions are run the way the tutor runs exercises (spark-submit, or
spark-pipelines for Declarative Pipelines files), so a passing run here means a
student who reaches the solution will see it work.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sparktutor.config.settings import ExecutionMode, Settings  # noqa: E402
from sparktutor.engine.executor import Executor  # noqa: E402
from sparktutor.engine.lesson_loader import load_course, load_lesson  # noqa: E402

COURSES = ROOT / "src" / "sparktutor" / "courses"


def selected(filters: list[str]) -> list[Path]:
    solutions = []
    for course_dir in sorted(p for p in COURSES.iterdir() if (p / "course.yaml").exists()):
        course = load_course(course_dir)
        for lesson_id in course.lessons:
            lesson_dir = course_dir / "lessons" / lesson_id
            key = f"{course.id}/{lesson_id}"
            if filters and not any(key == f or key.startswith(f + "/") for f in filters):
                continue
            # Every script step's solution (a lesson may have more than one)
            files = ["solution.py"]
            if (lesson_dir / "lesson.yaml").exists():
                files = [
                    step.solution_code for step in load_lesson(lesson_dir).steps
                    if step.cls == "script" and step.solution_code
                ] or files
            for name in dict.fromkeys(files):
                if (lesson_dir / name).exists():
                    solutions.append(lesson_dir / name)
    return solutions


async def main(filters: list[str]) -> int:
    settings = Settings(execution_mode=ExecutionMode.LOCAL, timeout_seconds=600)
    failures = []
    for solution in selected(filters):
        name = "/".join(solution.parts[-4:-1]).replace("/lessons", "")
        if solution.name != "solution.py":
            name += f" ({solution.name})"
        start = time.monotonic()
        result = await Executor(settings=settings).execute(solution.read_text())
        elapsed = time.monotonic() - start
        status = "ok" if result.success else "FAIL"
        print(f"{status:4} {elapsed:6.1f}s  {name}", flush=True)
        if not result.success:
            failures.append((name, result))
    for name, result in failures:
        print(f"\n==== {name} (exit {result.exit_code}) ====")
        print("\n".join(result.stdout.splitlines()[-30:]))
        errors = [l for l in result.stderr.splitlines() if " WARN " not in l]
        print("\n".join(errors[-40:]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
