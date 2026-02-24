"""Lesson instruction pane with markdown rendering and progress."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Markdown, Static


class LessonPane(Vertical):
    """Displays lesson instructions, progress, and depth indicator."""

    def __init__(self, **kwargs) -> None:
        super().__init__(id="lesson-pane", **kwargs)
        self.border_title = "Lesson"

    def compose(self) -> ComposeResult:
        yield Markdown("", id="lesson-content")
        yield Static("Step 0/0", id="lesson-progress")

    def set_content(self, markdown_text: str) -> None:
        md = self.query_one("#lesson-content", Markdown)
        md.update(markdown_text)

    def set_step_text(self, step_output: str, step_type: str = "text") -> None:
        """Format and display a step's content."""
        content = step_output

        if step_type == "mult_question":
            content = f"**Question:**\n\n{step_output}"
        elif step_type in ("cmd_question", "script"):
            content = f"**Exercise:**\n\n{step_output}"

        self.set_content(content)

    def set_choices(self, choices_str: str) -> None:
        """Display multiple choice options below the question."""
        md = self.query_one("#lesson-content", Markdown)
        choices = choices_str.split(";")
        choice_text = "\n".join(f"  **{i+1}.** {c.strip()}" for i, c in enumerate(choices))
        current = md._markdown  # Get current content
        md.update(f"{current}\n\n{choice_text}")

    def update_progress(self, current: int, total: int, depth: str = "") -> None:
        depth_stars = {"beginner": "★☆☆", "intermediate": "★★☆", "advanced": "★★★"}.get(depth, "")
        label = self.query_one("#lesson-progress", Static)
        label.update(f" Step {current + 1}/{total}  {depth_stars}")
