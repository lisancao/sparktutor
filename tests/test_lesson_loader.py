"""Tests for lesson loader."""

from sparktutor.engine.lesson_loader import load_course, load_lesson


def test_load_course(sample_course_dir):
    course = load_course(sample_course_dir)
    assert course.id == "test_course"
    assert course.title == "Test Course"
    assert len(course.lessons) == 1
    assert course.lessons[0] == "01_test_lesson"


def test_load_lesson(sample_lesson_dir):
    lesson = load_lesson(sample_lesson_dir)
    assert lesson.title == "Test Lesson"
    assert lesson.estimated_minutes == 5
    assert len(lesson.steps) == 6  # meta + 5 steps


def test_lesson_depth_filtering(sample_lesson_dir):
    lesson = load_lesson(sample_lesson_dir)

    beginner_steps = lesson.steps_for_depth("beginner")
    advanced_steps = lesson.steps_for_depth("advanced")

    # "all" steps appear in both, depth-specific only in their level
    beginner_outputs = [s.output for s in beginner_steps if s.cls != "meta"]
    advanced_outputs = [s.output for s in advanced_steps if s.cls != "meta"]

    assert "Print hello world" in beginner_outputs
    assert "Print hello world" not in advanced_outputs
    assert any(o.startswith("Define a class Pipeline") for o in advanced_outputs)


def test_step_types(sample_lesson_dir):
    lesson = load_lesson(sample_lesson_dir)
    types = {s.cls for s in lesson.steps}
    assert "meta" in types
    assert "text" in types
    assert "mult_question" in types
    assert "cmd_question" in types


def test_validation_parsing(sample_lesson_dir):
    lesson = load_lesson(sample_lesson_dir)
    # Find the advanced cmd_question with validation
    validated = [s for s in lesson.steps if s.validation]
    assert len(validated) == 1
    assert validated[0].validation[0].type == "ast_contains"
