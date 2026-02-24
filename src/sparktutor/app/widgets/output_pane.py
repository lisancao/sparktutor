"""Output pane for spark-submit output, chat input, and connection status."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Input, RichLog, Static

from sparktutor.engine.executor import ExecMode


class OutputPane(Vertical):
    """Displays spark-submit stdout/stderr with streaming, chat input, and connection status."""

    class ChatSubmitted(Message):
        """Fired when the user submits a chat message."""
        def __init__(self, question: str) -> None:
            super().__init__()
            self.question = question

    def __init__(self, **kwargs) -> None:
        super().__init__(id="output-pane", **kwargs)
        self.border_title = "Output"

    def compose(self) -> ComposeResult:
        yield RichLog(highlight=True, markup=True, id="output-log")
        yield Input(
            placeholder="Ask a question about this lesson... (Enter to send)",
            id="chat-input",
        )
        yield Static("● Detecting environment...", id="connection-status")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        question = event.value.strip()
        if question:
            event.input.clear()
            self.post_message(self.ChatSubmitted(question))

    def write_line(self, text: str) -> None:
        log = self.query_one("#output-log", RichLog)
        if text.startswith("[stderr]"):
            log.write(f"[red]{text}[/]")
        elif "Error" in text or "Exception" in text:
            log.write(f"[red]{text}[/]")
        elif "WARN" in text:
            log.write(f"[yellow]{text}[/]")
        else:
            log.write(text)

    def clear(self) -> None:
        log = self.query_one("#output-log", RichLog)
        log.clear()

    def set_connection_status(self, mode: ExecMode) -> None:
        status_map = {
            ExecMode.LAKEHOUSE: "[green]●[/] spark-master-41 (lakehouse)",
            ExecMode.LOCAL: "[yellow]●[/] local spark-submit",
            ExecMode.DRY_RUN: "[red]●[/] dry-run (syntax only)",
        }
        label = self.query_one("#connection-status", Static)
        label.update(f" {status_map.get(mode, '● unknown')}")

    def show_running(self) -> None:
        status = self.query_one("#connection-status", Static)
        status.update(" [yellow]⟳[/] Running spark-submit...")

    def show_complete(self, success: bool) -> None:
        status = self.query_one("#connection-status", Static)
        if success:
            status.update(" [green]✓[/] Execution complete")
        else:
            status.update(" [red]✗[/] Execution failed")
