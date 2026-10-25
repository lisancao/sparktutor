"""Content checks that apply to every lesson in every course."""

from pathlib import Path

import pytest
import yaml

COURSES = Path(__file__).resolve().parent.parent / "src" / "sparktutor" / "courses"
LESSONS = sorted(COURSES.glob("*/lessons/*/lesson.yaml"))


@pytest.mark.parametrize("lesson", LESSONS, ids=lambda p: f"{p.parts[-4]}/{p.parts[-2]}")
def test_quiz_answers_are_choices(lesson):
    # The lesson panel splits AnswerChoices on ";", so a ";" inside an answer
    # makes the question impossible to answer.
    for step in yaml.safe_load(lesson.read_text()):
        if step.get("Class") == "mult_question":
            choices = [c.strip() for c in str(step["AnswerChoices"]).split(";")]
            assert str(step["CorrectAnswer"]).strip() in choices, step["Output"]
