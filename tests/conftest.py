"""Shared fixtures for SparkTutor tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def sample_course_dir(tmp_path):
    """Create a minimal course directory for testing."""
    course_dir = tmp_path / "test_course"
    course_dir.mkdir()

    # course.yaml
    course_data = {
        "course": {
            "id": "test_course",
            "title": "Test Course",
            "description": "A test course",
            "version": "1.0.0",
            "requires_lakehouse": False,
            "lessons": ["01_test_lesson"],
        }
    }
    with open(course_dir / "course.yaml", "w") as f:
        yaml.dump(course_data, f)

    # lesson directory
    lesson_dir = course_dir / "lessons" / "01_test_lesson"
    lesson_dir.mkdir(parents=True)

    lesson_steps = [
        {"Class": "meta", "Lesson": "Test Lesson", "EstimatedMinutes": 5},
        {"Class": "text", "Depth": "all", "Output": "Welcome to the test lesson."},
        {
            "Class": "mult_question",
            "Depth": "all",
            "Output": "What is 2+2?",
            "AnswerChoices": "3;4;5;6",
            "CorrectAnswer": "4",
            "Hint": "It's an even number.",
        },
        {
            "Class": "cmd_question",
            "Depth": "all",
            "Output": "Create a variable x = 42",
            "CorrectAnswer": "x = 42",
            "Hint": "Assign 42 to x.",
        },
        {
            "Class": "cmd_question",
            "Depth": "beginner",
            "Output": "Print hello world",
            "CorrectAnswer": "print('hello world')",
            "Hint": "Use the print function.",
        },
        {
            "Class": "cmd_question",
            "Depth": "advanced",
            "Output": "Define a class Pipeline with __init__ taking name.",
            "CorrectAnswer": "class Pipeline:\n    def __init__(self, name):\n        self.name = name",
            "Validation": [
                "ast_contains(class_def='Pipeline')",
                "ast_contains(method='__init__')",
            ],
            "Hint": "Define a class with an __init__ method.",
        },
    ]
    with open(lesson_dir / "lesson.yaml", "w") as f:
        yaml.dump(lesson_steps, f)

    return course_dir


@pytest.fixture
def sample_lesson_dir(sample_course_dir):
    return sample_course_dir / "lessons" / "01_test_lesson"
