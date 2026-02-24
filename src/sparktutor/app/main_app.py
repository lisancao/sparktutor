"""SparkTutor main Textual application."""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from sparktutor.app.screens.home_screen import HomeScreen
from sparktutor.app.screens.lesson_screen import LessonScreen
from sparktutor.config.settings import Settings
from sparktutor.courses.registry import CourseRegistry
from sparktutor.engine.adaptive import Depth
from sparktutor.engine.evaluator import Evaluator
from sparktutor.engine.executor import Executor
from sparktutor.engine.lesson_loader import CourseMeta
from sparktutor.state.progress import ProgressStore


class SparkTutorApp(App):
    """Interactive Spark 4.1 learning environment."""

    TITLE = "SparkTutor"
    SUB_TITLE = "Interactive Spark 4.1 Learning"

    CSS_PATH = Path(__file__).parent / "css" / "sparktutor.tcss"

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def __init__(self, force_dry_run: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.settings = Settings.load()
        self.executor = Executor(settings=self.settings, force_dry_run=force_dry_run)
        self.evaluator = Evaluator(settings=self.settings)
        self.registry = CourseRegistry()
        self.progress = ProgressStore()

    def on_mount(self) -> None:
        self.push_screen(HomeScreen(registry=self.registry, progress=self.progress))
        # Detect execution mode asynchronously
        self.run_worker(self._detect_mode())

    async def _detect_mode(self) -> None:
        mode = await self.executor.detect_mode()
        self.sub_title = f"Spark 4.1 Learning — {mode.value}"

    def start_course(
        self, course: CourseMeta, depth: Depth, resume_lesson_idx: int = 0,
    ) -> None:
        """Called by HomeScreen to launch a lesson."""
        screen = LessonScreen(
            course=course,
            depth=depth,
            executor=self.executor,
            evaluator=self.evaluator,
            progress=self.progress,
            start_lesson_idx=resume_lesson_idx,
        )
        self.push_screen(screen)
