"""Structural checks for the spark_4_whats_new course.

These do not run Spark (scripts/verify_solutions.py does that); they make
sure the course is discoverable, every lesson parses, questions are
answerable, exercises point at real files, and the prose follows the
course's writing rules.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sparktutor.courses.registry import CourseRegistry
from sparktutor.engine.lesson_loader import load_course, load_lesson

COURSE_ID = "spark_4_whats_new"
COURSE_DIR = Path(__file__).resolve().parent.parent / "src" / "sparktutor" / "courses" / COURSE_ID
EM_DASH = "—"


def lesson_dirs():
    course = load_course(COURSE_DIR)
    return [COURSE_DIR / "lessons" / lesson_id for lesson_id in course.lessons]


def test_course_is_discovered():
    course = CourseRegistry().get_course(COURSE_ID)
    assert course is not None
    assert course.version == "1.0.0"
    assert course.requires_lakehouse is False
    assert any('pyspark[connect]==4.2.0' in p for p in course.prerequisites)


def test_course_lists_existing_lessons():
    course = load_course(COURSE_DIR)
    on_disk = sorted(p.name for p in (COURSE_DIR / "lessons").iterdir() if p.is_dir())
    assert course.lessons == on_disk
    assert len(course.lessons) >= 6


@pytest.mark.parametrize("lesson_dir", lesson_dirs(), ids=lambda p: p.name)
def test_lesson_structure(lesson_dir):
    lesson = load_lesson(lesson_dir)
    assert lesson.steps[0].cls == "meta" and lesson.title
    classes = [s.cls for s in lesson.steps]
    assert classes.count("mult_question") + classes.count("cmd_question") >= 3
    assert "script" in classes
    depths = {s.depth for s in lesson.steps if s.cls == "text"}
    assert {"all", "beginner", "intermediate", "advanced"} <= depths
    assert {s.depth for s in lesson.steps} <= {"all", "beginner", "intermediate", "advanced"}


@pytest.mark.parametrize("lesson_dir", lesson_dirs(), ids=lambda p: p.name)
def test_questions_are_answerable(lesson_dir):
    lesson = load_lesson(lesson_dir)
    for step in lesson.steps:
        if step.cls == "mult_question":
            choices = [c.strip() for c in step.answer_choices.split(";")]
            assert step.correct_answer in choices, step.output
            assert len(choices) == len(set(choices)) >= 3, step.output
            assert step.hint
        elif step.cls == "cmd_question":
            ast.parse(step.correct_answer)  # must be valid Python
            assert step.hint


@pytest.mark.parametrize("lesson_dir", lesson_dirs(), ids=lambda p: p.name)
def test_script_files_exist_and_parse(lesson_dir):
    lesson = load_lesson(lesson_dir)
    scripts = [s for s in lesson.steps if s.cls == "script"]
    for step in scripts:
        for name in (step.starter_code, step.solution_code):
            path = lesson_dir / name
            assert path.exists(), path
            ast.parse(path.read_text())
    starter = (lesson_dir / "starter.py").read_text()
    solution = (lesson_dir / "solution.py").read_text()
    assert "TODO" in starter and "TODO" not in solution
    # The harness the student runs must match the one the solution is verified with.
    marker = "if __name__ == \"__main__\":"
    assert starter.split(marker)[1] == solution.split(marker)[1]


@pytest.mark.parametrize(
    "path",
    sorted(p for p in COURSE_DIR.rglob("*") if p.suffix in {".yaml", ".py"}),
    ids=lambda p: str(p.relative_to(COURSE_DIR)),
)
def test_writing_rules(path):
    text = path.read_text()
    assert EM_DASH not in text, f"em dash in {path}"
    if path.suffix == ".py":
        assert text.isascii(), f"non-ASCII characters in {path}"
