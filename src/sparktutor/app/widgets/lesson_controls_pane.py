"""Zone 2 — Lesson controls button grid with single-letter shortcuts."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button


class LessonControlsPane(Vertical):
    """Always-visible button grid for lesson actions.

    Single-letter shortcuts only fire when this pane is focused.
    Buttons are clickable from any zone.
    """

    can_focus = True
    can_focus_children = False

    BINDINGS = [
        Binding("r", "do_run",        "Run",     show=False),
        Binding("s", "do_submit",     "Submit",  show=False),
        Binding("h", "do_hint",       "Hint",    show=False),
        Binding("b", "do_back",       "Back",    show=False),
        Binding("n", "do_next",       "Next",    show=False),
        Binding("w", "do_save",       "Save",    show=False),
        Binding("e", "do_edit",       "Edit",    show=False),
        Binding("p", "do_sandbox",    "Sandbox", show=False),
        Binding("f", "do_feedback",   "Feedback", show=False),
        Binding("q", "do_quit",       "Quit",    show=False),
        Binding("escape", "next_zone", "Next zone", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(id="controls-pane", **kwargs)
        self.border_title = "Controls"

    def compose(self) -> ComposeResult:
        with Horizontal(classes="ctrl-row"):
            yield Button("[r]un", id="ctrl-run", classes="ctrl-btn", variant="default")
            yield Button("[s]ubmit", id="ctrl-submit", classes="ctrl-btn", variant="success")
            yield Button("[h]int", id="ctrl-hint", classes="ctrl-btn", variant="default")
        with Horizontal(classes="ctrl-row"):
            yield Button("[b]ack", id="ctrl-back", classes="ctrl-btn", variant="default")
            yield Button("[n]ext", id="ctrl-next", classes="ctrl-btn", variant="primary")
            yield Button("sa[w]e", id="ctrl-save", classes="ctrl-btn", variant="default")
        with Horizontal(classes="ctrl-row"):
            yield Button("[e]dit", id="ctrl-edit", classes="ctrl-btn", variant="default")
            yield Button("[p]ause", id="ctrl-sandbox", classes="ctrl-btn", variant="warning")
            yield Button("[q]uit", id="ctrl-quit", classes="ctrl-btn", variant="error")

    # ── Button click handler ──

    _BUTTON_ACTIONS = {
        "ctrl-run":     "run_code",
        "ctrl-submit":  "submit_code",
        "ctrl-hint":    "show_hint",
        "ctrl-back":    "prev_step",
        "ctrl-next":    "next_step",
        "ctrl-save":    "save_progress",
        "ctrl-edit":    "edit_code",
        "ctrl-sandbox": "toggle_sandbox",
        "ctrl-quit":    "go_home",
    }

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action = self._BUTTON_ACTIONS.get(event.button.id or "")
        if action:
            self.screen.run_action(action)

    # ── Single-letter binding actions (delegate to screen) ──

    def action_do_run(self) -> None:
        self.screen.run_action("run_code")

    def action_do_submit(self) -> None:
        self.screen.run_action("submit_code")

    def action_do_hint(self) -> None:
        self.screen.run_action("show_hint")

    def action_do_back(self) -> None:
        self.screen.run_action("prev_step")

    def action_do_next(self) -> None:
        self.screen.run_action("next_step")

    def action_do_save(self) -> None:
        self.screen.run_action("save_progress")

    def action_do_edit(self) -> None:
        self.screen.run_action("edit_code")

    def action_do_sandbox(self) -> None:
        self.screen.run_action("toggle_sandbox")

    def action_do_feedback(self) -> None:
        self.screen.run_action("toggle_feedback")

    def action_do_quit(self) -> None:
        self.screen.run_action("go_home")

    def action_next_zone(self) -> None:
        self.screen.focus_next()
