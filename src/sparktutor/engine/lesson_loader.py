"""YAML lesson parser for SparkTutor."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class CourseMeta:
    id: str
    title: str
    description: str
    version: str
    requires_lakehouse: bool = False
    lessons: list[str] = field(default_factory=list)


@dataclass
class ValidationRule:
    type: str  # "ast_contains", "claude_review", "omnitest"
    params: dict = field(default_factory=dict)


@dataclass
class Step:
    cls: str  # "meta", "text", "mult_question", "cmd_question", "script"
    depth: str = "all"  # "all", "beginner", "intermediate", "advanced"
    output: str = ""
    answer_choices: Optional[str] = None  # semicolon-separated for mult_question
    correct_answer: Optional[str] = None
    hint: Optional[str] = None
    starter_code: Optional[str] = None  # filename for script steps
    solution_code: Optional[str] = None  # filename for script steps
    validation: list[ValidationRule] = field(default_factory=list)
    requires_execution: bool = False
    # Meta fields
    lesson_title: Optional[str] = None
    estimated_minutes: Optional[int] = None


@dataclass
class Lesson:
    id: str
    title: str
    estimated_minutes: int
    steps: list[Step]
    base_path: Path  # directory containing lesson.yaml

    def steps_for_depth(self, depth: str) -> list[Step]:
        """Filter steps by depth level. 'all' steps always included."""
        return [s for s in self.steps if s.depth in ("all", depth)]


def _parse_validation(raw) -> list[ValidationRule]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [ValidationRule(type=raw.get("type", ""), params=raw)]
    if isinstance(raw, list):
        rules = []
        for item in raw:
            if isinstance(item, str):
                # Parse "ast_contains(class_def='Pipeline')" style
                if "(" in item:
                    func_name = item[: item.index("(")]
                    rules.append(ValidationRule(type=func_name, params={"expr": item}))
                else:
                    rules.append(ValidationRule(type=item, params={}))
            elif isinstance(item, dict):
                rules.append(ValidationRule(type=item.get("type", ""), params=item))
        return rules
    return []


def load_course(course_dir: Path) -> CourseMeta:
    """Load course.yaml from a course directory."""
    course_file = course_dir / "course.yaml"
    with open(course_file) as f:
        data = yaml.safe_load(f)

    c = data["course"]
    return CourseMeta(
        id=c["id"],
        title=c["title"],
        description=c["description"],
        version=c["version"],
        requires_lakehouse=c.get("requires_lakehouse", False),
        lessons=c.get("lessons", []),
    )


def load_lesson(lesson_dir: Path) -> Lesson:
    """Load a lesson.yaml from a lesson directory."""
    lesson_file = lesson_dir / "lesson.yaml"
    with open(lesson_file) as f:
        raw_steps = yaml.safe_load(f)

    title = ""
    estimated = 15
    steps: list[Step] = []

    for raw in raw_steps:
        cls = raw.get("Class", "text")

        if cls == "meta":
            title = raw.get("Lesson", "")
            estimated = raw.get("EstimatedMinutes", 15)
            steps.append(Step(
                cls="meta",
                lesson_title=title,
                estimated_minutes=estimated,
            ))
            continue

        step = Step(
            cls=cls,
            depth=raw.get("Depth", "all"),
            output=raw.get("Output", ""),
            answer_choices=raw.get("AnswerChoices"),
            correct_answer=raw.get("CorrectAnswer"),
            hint=raw.get("Hint"),
            starter_code=raw.get("StarterCode"),
            solution_code=raw.get("SolutionCode"),
            validation=_parse_validation(raw.get("Validation")),
            requires_execution=raw.get("RequiresExecution", False),
        )
        steps.append(step)

    return Lesson(
        id=lesson_dir.name,
        title=title,
        estimated_minutes=estimated,
        steps=steps,
        base_path=lesson_dir,
    )
