"""Home screen — course selection, depth/goal setting, and resume."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, OptionList, Static
from textual.widgets.option_list import Option

from sparktutor.courses.registry import CourseRegistry
from sparktutor.engine.adaptive import Depth
from sparktutor.engine.lesson_loader import CourseMeta
from sparktutor.state.progress import ProgressStore

_DEPTH_MAP = {
    "beginner": Depth.BEGINNER,
    "intermediate": Depth.INTERMEDIATE,
    "advanced": Depth.ADVANCED,
}


class HomeScreen(Screen):
    """Course selection and experience level picker."""

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    CSS = """
    #home-container {
        align: center middle;
        padding: 2 4;
    }
    """

    def __init__(
        self,
        registry: CourseRegistry,
        progress: ProgressStore,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.registry = registry
        self.progress = progress
        self.selected_course: CourseMeta | None = None
        self.selected_depth: Depth = Depth.BEGINNER
        self._resume_info: dict | None = None  # Populated when a course has saved progress

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="home-container"):
            yield Static(
                "╔═╗┌─┐┌─┐┬─┐┬┌─  ╔╦╗┬ ┬┌┬┐┌─┐┬─┐\n"
                "╚═╗├─┘├─┤├┬┘├┴┐   ║ │ │ │ │ │├┬┘\n"
                "╚═╝┴  ┴ ┴┴└─┴ ┴   ╩ └─┘ ┴ └─┘┴└─",
                id="welcome-art",
            )
            yield Static(
                "[bold]Interactive Spark 4.1 Learning Environment[/]\n"
                "[dim]Powered by Claude • Backed by lakehouse-stack[/]",
                id="home-subtitle",
            )

            yield Label("\n[bold]Select a course:[/]")
            courses = self.registry.list_courses()
            options = []
            for c in courses:
                summary = self.progress.get_course_summary(c.id, c.lessons)
                if summary.get("started"):
                    done = summary["lessons_completed"]
                    total = summary["total_lessons"]
                    pct = int(done / total * 100) if total else 0
                    bar = self._progress_bar(done, total)
                    options.append(Option(
                        f"{c.title}  {bar} {pct}%\n"
                        f"  [dim]{c.description}[/]",
                        id=c.id,
                    ))
                else:
                    options.append(Option(
                        f"{c.title}\n  [dim]{c.description}[/]",
                        id=c.id,
                    ))
            yield OptionList(*options, id="course-list")

            # Progress info (hidden until course selected)
            yield Static("", id="progress-info")

            yield Label("\n[bold]What's your experience level?[/]")
            with Vertical(id="depth-buttons"):
                yield Button("★☆☆ New to Spark", id="depth-beginner", variant="default")
                yield Button("★★☆ Know the basics", id="depth-intermediate", variant="default")
                yield Button("★★★ Challenge me", id="depth-advanced", variant="default")

            yield Button("Continue →", id="continue-btn", variant="warning", disabled=True)
            yield Button("Start Fresh →", id="start-btn", variant="primary", disabled=True)

        yield Footer()

    @staticmethod
    def _progress_bar(done: int, total: int, width: int = 10) -> str:
        filled = int(done / total * width) if total else 0
        return "[green]" + "█" * filled + "[/][dim]░" * (width - filled) + "[/]"

    def on_mount(self) -> None:
        # Hide continue button initially
        self.query_one("#continue-btn", Button).display = False
        self.query_one("#progress-info", Static).display = False

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        courses = self.registry.list_courses()
        for c in courses:
            if c.id == event.option.id:
                self.selected_course = c
                break

        self._check_saved_progress()
        self._update_buttons()

    def _check_saved_progress(self) -> None:
        """Check if selected course has saved progress."""
        if self.selected_course is None:
            self._resume_info = None
            return

        summary = self.progress.get_course_summary(
            self.selected_course.id, self.selected_course.lessons,
        )

        if summary.get("started"):
            self._resume_info = summary
            # Auto-select the saved depth
            saved_depth = _DEPTH_MAP.get(summary["depth"], Depth.BEGINNER)
            self.selected_depth = saved_depth
            depth_id = f"depth-{summary['depth']}"
            self._highlight_depth(depth_id)

            # Show progress info
            done = summary["lessons_completed"]
            total = summary["total_lessons"]
            lesson_idx = summary["current_lesson_idx"]
            lesson_id = summary.get("current_lesson_id", "?")
            info = self.query_one("#progress-info", Static)
            info.update(
                f"\n[bold #FF6F00]Saved progress:[/] "
                f"Lesson {lesson_idx + 1}/{total} — [dim]{lesson_id}[/] "
                f"({done} completed)"
            )
            info.display = True
            self.query_one("#continue-btn", Button).display = True
        else:
            self._resume_info = None
            self.query_one("#progress-info", Static).display = False
            self.query_one("#continue-btn", Button).display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "depth-beginner":
            self.selected_depth = Depth.BEGINNER
            self._highlight_depth("depth-beginner")
        elif event.button.id == "depth-intermediate":
            self.selected_depth = Depth.INTERMEDIATE
            self._highlight_depth("depth-intermediate")
        elif event.button.id == "depth-advanced":
            self.selected_depth = Depth.ADVANCED
            self._highlight_depth("depth-advanced")
        elif event.button.id == "continue-btn" and self.selected_course and self._resume_info:
            self.app.start_course(
                self.selected_course,
                self.selected_depth,
                resume_lesson_idx=self._resume_info["current_lesson_idx"],
            )
        elif event.button.id == "start-btn" and self.selected_course:
            # Reset progress if starting fresh
            if self._resume_info:
                self.progress.reset_course(self.selected_course.id)
            self.app.start_course(self.selected_course, self.selected_depth)

        self._update_buttons()

    def _highlight_depth(self, active_id: str) -> None:
        for btn_id in ("depth-beginner", "depth-intermediate", "depth-advanced"):
            btn = self.query_one(f"#{btn_id}", Button)
            btn.variant = "primary" if btn_id == active_id else "default"

    def _update_buttons(self) -> None:
        has_course = self.selected_course is not None
        self.query_one("#start-btn", Button).disabled = not has_course
        self.query_one("#continue-btn", Button).disabled = not has_course
