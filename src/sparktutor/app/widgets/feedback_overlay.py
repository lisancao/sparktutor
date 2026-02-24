"""Feedback overlay showing evaluation results and suggestions."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from sparktutor.engine.evaluator import EvalResult, FeedbackItem


class FeedbackOverlay(Vertical):
    """Floating panel showing line-level errors, suggestions, and encouragement."""

    def __init__(self, **kwargs) -> None:
        super().__init__(id="feedback-overlay", **kwargs)
        self.border_title = "Feedback"

    def compose(self) -> ComposeResult:
        yield Static("", id="encouragement")
        yield VerticalScroll(id="feedback-items")

    def show_result(self, result: EvalResult) -> None:
        """Populate the overlay with evaluation results."""
        # Encouragement
        enc = self.query_one("#encouragement", Static)
        if result.passed:
            enc.update(f"[green bold]{result.encouragement or 'Correct!'}[/]")
        else:
            enc.update(f"[yellow]{result.encouragement or 'Not quite — check the feedback below.'}[/]")

        # Feedback items
        container = self.query_one("#feedback-items", VerticalScroll)
        container.remove_children()

        for item in result.feedback:
            widget = self._make_feedback_widget(item)
            container.mount(widget)

        self.add_class("visible")

    def _make_feedback_widget(self, item: FeedbackItem) -> Static:
        severity_style = {
            "error": "red",
            "warning": "yellow",
            "info": "cyan",
            "success": "green",
        }.get(item.severity, "white")

        parts = []
        if item.line:
            parts.append(f"[dim]Line {item.line}:[/] ")
        parts.append(f"[{severity_style}]{item.message}[/]")
        if item.suggestion:
            parts.append(f"\n  [dim italic]→ {item.suggestion}[/]")

        return Static("".join(parts), classes=f"feedback-item feedback-{item.severity}")

    def hide(self) -> None:
        self.remove_class("visible")

    def toggle(self) -> None:
        if self.has_class("visible"):
            self.hide()
        else:
            self.add_class("visible")
