"""Course discovery and registry."""

from __future__ import annotations

from pathlib import Path

from sparktutor.engine.lesson_loader import CourseMeta, load_course


class CourseRegistry:
    """Discovers and loads courses from the courses directory."""

    def __init__(self, courses_dir: Path | None = None):
        self.courses_dir = courses_dir or (
            Path(__file__).parent
        )

    def list_courses(self) -> list[CourseMeta]:
        """Discover all courses with a course.yaml."""
        courses = []
        for path in sorted(self.courses_dir.iterdir()):
            if path.is_dir() and (path / "course.yaml").exists():
                try:
                    courses.append(load_course(path))
                except Exception:
                    pass
        return courses

    def get_course(self, course_id: str) -> CourseMeta | None:
        for course in self.list_courses():
            if course.id == course_id:
                return course
        return None
