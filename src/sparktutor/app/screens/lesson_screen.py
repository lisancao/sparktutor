"""Main lesson workspace — three-zone layout: editor, controls, output."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from sparktutor.app.widgets.code_editor import CodeEditor
from sparktutor.app.widgets.feedback_overlay import FeedbackOverlay
from sparktutor.app.widgets.lesson_controls_pane import LessonControlsPane
from sparktutor.app.widgets.lesson_pane import LessonPane
from sparktutor.app.widgets.output_pane import OutputPane
from sparktutor.engine.adaptive import Depth, LearnerProfile
from sparktutor.engine.evaluator import Evaluator
from sparktutor.engine.executor import Executor
from sparktutor.engine.lesson_loader import CourseMeta
from sparktutor.engine.lesson_runner import LessonRunner
from sparktutor.state.progress import ProgressStore


# Keybindings bar text per zone
_ZONE_KEYS = {
    "code-editor": (
        " [bold]Esc[/] → controls | "
        "[bold]ctrl+r[/] run | [bold]ctrl+s[/] submit | "
        "[bold]ctrl+1/2/3[/] zones"
    ),
    "controls-pane": (
        " [bold]r[/] run  [bold]s[/] submit  [bold]n[/] next  "
        "[bold]b[/] back  [bold]h[/] hint  [bold]w[/] save  "
        "[bold]q[/] quit | [bold]Esc[/] → question"
    ),
    "output-pane": (
        " [bold]Enter[/] send | [bold]Esc[/] → editor | "
        "[bold]ctrl+r[/] run | [bold]ctrl+s[/] submit"
    ),
}
_DEFAULT_KEYS = (
    " [bold]ctrl+1[/] editor | [bold]ctrl+2[/] controls | "
    "[bold]ctrl+3[/] question | [bold]ctrl+r[/] run | [bold]ctrl+s[/] submit"
)


class LessonScreen(Screen):
    """Main learning workspace with three input zones: editor, controls, output."""

    BINDINGS = [
        Binding("ctrl+underscore", "focus_editor", "Editor", show=False),      # ctrl+1 in many terminals
        Binding("f5", "focus_editor", "Zone 1", show=False),
        Binding("f6", "focus_controls", "Zone 2", show=False),
        Binding("f7", "focus_question", "Zone 3", show=False),
        Binding("ctrl+r", "run_code", "Run", show=True),
        Binding("ctrl+s", "submit_code", "Submit", show=True),
        Binding("f2", "save_progress", "Save", show=True),
    ]

    def __init__(
        self,
        course: CourseMeta,
        depth: Depth,
        executor: Executor,
        evaluator: Evaluator,
        progress: Optional[ProgressStore] = None,
        start_lesson_idx: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.course = course
        self.depth = depth
        self.executor = executor
        self.evaluator = evaluator
        self.progress = progress or ProgressStore()
        self.runner: Optional[LessonRunner] = None
        self._current_lesson_idx = start_lesson_idx
        self._sandbox_mode = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="lesson-layout"):
            yield LessonPane()
            with Horizontal(id="bottom-panes"):
                yield CodeEditor()
                yield LessonControlsPane()
                yield OutputPane()
        yield FeedbackOverlay()
        yield Static(_DEFAULT_KEYS, id="keybindings-bar")
        yield Footer()

    def on_mount(self) -> None:
        self._start_lesson(self._current_lesson_idx)
        # Start with code editor focused
        self.query_one("#code-area").focus()

    # ── Focus zone management ──

    def watch_focused(self) -> None:
        """Update keybindings bar when focus changes between zones."""
        focused = self.focused
        if focused is None:
            return

        # Walk up to find which zone container the focused widget is in
        zone_id = None
        widget = focused
        while widget is not None:
            wid = getattr(widget, "id", None)
            if wid in _ZONE_KEYS:
                zone_id = wid
                break
            widget = getattr(widget, "parent", None)

        bar = self.query_one("#keybindings-bar", Static)
        if zone_id:
            bar.update(_ZONE_KEYS[zone_id])
        else:
            bar.update(_DEFAULT_KEYS)

    def on_descendant_focus(self, event) -> None:
        """Called when any descendant gains focus — update the keybindings bar."""
        self.watch_focused()

    def action_focus_editor(self) -> None:
        """Focus Zone 1 — code editor."""
        self.query_one("#code-area").focus()

    def action_focus_controls(self) -> None:
        """Focus Zone 2 — lesson controls."""
        self.query_one("#controls-pane").focus()

    def action_focus_question(self) -> None:
        """Focus Zone 3 — chat input."""
        self.query_one("#chat-input").focus()

    # ── Lesson lifecycle ──

    def _start_lesson(self, lesson_idx: int) -> None:
        """Initialize the runner for a specific lesson."""
        if lesson_idx >= len(self.course.lessons):
            self._show_course_complete()
            return

        self._current_lesson_idx = lesson_idx
        lesson_id = self.course.lessons[lesson_idx]
        courses_dir = Path(__file__).parent.parent.parent / "courses"
        lesson_dir = courses_dir / self.course.id / "lessons" / lesson_id

        profile = LearnerProfile(depth=self.depth)
        self.runner = LessonRunner(
            course_id=self.course.id,
            executor=self.executor,
            evaluator=self.evaluator,
            progress=self.progress,
            profile=profile,
        )
        self.runner.load_lesson(lesson_dir)
        self._present_current_step()

    def _present_current_step(self) -> None:
        """Update all panes for the current step."""
        if self.runner is None or self.runner.state is None:
            return

        step = self.runner.current_step()
        if step is None:
            self._advance_to_next_lesson()
            return

        state = self.runner.state
        lesson_pane = self.query_one(LessonPane)
        code_editor = self.query_one(CodeEditor)
        feedback = self.query_one(FeedbackOverlay)

        # Update lesson pane
        lesson_pane.set_step_text(step.output, step.cls)
        if step.answer_choices:
            lesson_pane.set_choices(step.answer_choices)
        lesson_pane.update_progress(
            state.current_index, len(state.filtered_steps), self.depth.value,
        )

        # Check for restored code from a previous session
        restored = self.runner.get_restored_code()
        if restored:
            code_editor.set_starter_code(restored)
            output = self.query_one(OutputPane)
            output.write_line("[dim]Restored saved code from previous session.[/]")
        else:
            # Load starter code
            starter = self.runner.get_starter_code()
            if starter:
                code_editor.set_starter_code(starter)
            else:
                code_editor.clear_errors()
                if step.cls == "text":
                    code_editor.set_starter_code("# Press n or click Next to continue...")
                elif step.cls == "mult_question":
                    code_editor.set_starter_code(
                        "# Type the number of your answer (e.g., 1)\n"
                        "# Then press s or click Submit"
                    )

        # Hide feedback overlay
        feedback.hide()

        # Update title
        self.title = f"SparkTutor — {self.runner.state.lesson.title}"
        if self._sandbox_mode:
            self.title += " [SANDBOX]"

    # ── Save ──

    def _save_current(self) -> None:
        """Save current code and step progress to the database."""
        if self.runner is None or self.runner.state is None:
            return
        code = self.query_one(CodeEditor).code
        self.runner._save_progress(code)

    def action_save_progress(self) -> None:
        """Explicitly save current code and progress."""
        self._save_current()
        output = self.query_one(OutputPane)
        output.write_line("[green]Progress saved.[/]")

    def action_save_and_quit(self) -> None:
        """Save and return to home screen."""
        self._save_current()
        output = self.query_one(OutputPane)
        output.write_line("[green]Progress saved.[/]")
        self.app.pop_screen()

    # ── Actions ──

    def action_edit_code(self) -> None:
        """Open the code in $EDITOR (nvim)."""
        self.query_one(CodeEditor).open_in_editor()

    async def action_run_code(self) -> None:
        """Execute current code without evaluating."""
        code = self.query_one(CodeEditor).code
        output = self.query_one(OutputPane)
        output.clear()
        output.show_running()

        result = await self.executor.execute(code, on_output=output.write_line)
        output.show_complete(result.success)

    async def action_submit_code(self) -> None:
        """Submit code for evaluation."""
        if self._sandbox_mode:
            output = self.query_one(OutputPane)
            output.write_line("[yellow]Sandbox mode — press p to resume lesson before submitting.[/]")
            return

        if self.runner is None:
            return

        step = self.runner.current_step()
        if step is None:
            return

        code_editor = self.query_one(CodeEditor)
        output = self.query_one(OutputPane)
        feedback_overlay = self.query_one(FeedbackOverlay)

        code = code_editor.code.strip()

        # For text steps, just advance
        if step.cls == "text":
            self.action_next_step()
            return

        # For mult_question, extract the choice
        if step.cls == "mult_question" and step.answer_choices:
            choices = [c.strip() for c in step.answer_choices.split(";")]
            try:
                idx = int(code.strip()) - 1
                if 0 <= idx < len(choices):
                    code = choices[idx]
            except ValueError:
                pass  # User typed the answer directly

        # Execute if needed
        if step.requires_execution:
            output.clear()
            output.show_running()

        result = await self.runner.submit(code)

        # Show feedback
        feedback_overlay.show_result(result)

        # Mark error lines
        error_lines = {f.line for f in result.feedback if f.line and f.severity == "error"}
        code_editor.mark_error_lines(error_lines)

        # If passed, show success and prepare for next
        if result.passed:
            output.write_line("[green]✓ Step complete![/]")

    def action_show_hint(self) -> None:
        """Show hint for current step."""
        if self.runner is None:
            return
        hint = self.runner.get_hint()
        output = self.query_one(OutputPane)
        if hint:
            output.write_line(f"[cyan]Hint: {hint}[/]")
        else:
            output.write_line("[dim]No hint available for this step.[/]")

    def action_next_step(self) -> None:
        """Advance to the next step."""
        if self._sandbox_mode:
            output = self.query_one(OutputPane)
            output.write_line("[yellow]Sandbox mode — press p to resume lesson first.[/]")
            return

        if self.runner is None:
            return

        state = self.runner.state
        if state is None:
            return

        # Auto-save before advancing
        self._save_current()

        # Allow advancing text steps without submission
        step = self.runner.current_step()
        if step and step.cls == "text":
            self.runner.advance()
            self._present_current_step()
            return

        # For question steps, only advance if passed
        if state.last_result and state.last_result.passed:
            self.runner.advance()
            self._present_current_step()
        else:
            output = self.query_one(OutputPane)
            output.write_line("[yellow]Submit a correct answer before advancing.[/]")

    def action_prev_step(self) -> None:
        """Go back to the previous step."""
        if self._sandbox_mode:
            output = self.query_one(OutputPane)
            output.write_line("[yellow]Sandbox mode — press p to resume lesson first.[/]")
            return

        if self.runner is None:
            return

        # Auto-save before going back
        self._save_current()

        result = self.runner.go_back()
        if result is not None:
            self._present_current_step()
        else:
            output = self.query_one(OutputPane)
            output.write_line("[dim]Already at the first step.[/]")

    def action_toggle_sandbox(self) -> None:
        """Toggle sandbox/pause mode for free experimentation."""
        self._sandbox_mode = not self._sandbox_mode
        output = self.query_one(OutputPane)
        keybindings = self.query_one("#keybindings-bar", Static)

        if self._sandbox_mode:
            output.write_line(
                "\n[bold #FF6F00]── Sandbox Mode ──[/]\n"
                "[dim]Lesson paused. Edit and run code freely.\n"
                "Press [bold]p[/bold] in controls to resume the lesson.[/]"
            )
            keybindings.update(
                " [bold #FF6F00]SANDBOX[/]  "
                "[bold]ctrl+r[/] run  [bold]ctrl+s[/] submit  "
                "[bold]p[/] resume  [bold]q[/] quit"
            )
            self.title = "SparkTutor — Sandbox"
            if self.runner and self.runner.state:
                self.title = f"SparkTutor — {self.runner.state.lesson.title} [SANDBOX]"
        else:
            output.write_line("\n[green]── Resuming Lesson ──[/]")
            self.watch_focused()  # Restore zone-appropriate bar
            if self.runner and self.runner.state:
                self.title = f"SparkTutor — {self.runner.state.lesson.title}"

    def action_toggle_feedback(self) -> None:
        """Toggle the feedback overlay."""
        self.query_one(FeedbackOverlay).toggle()

    def action_go_home(self) -> None:
        """Auto-save and return to home screen."""
        self._save_current()
        self.app.pop_screen()

    def action_show_help(self) -> None:
        """Show available commands in the output pane."""
        output = self.query_one(OutputPane)
        output.write_line("\n[bold #E25A1C]── Controls ──[/]")
        output.write_line("  [bold]r[/] / ctrl+r  Run code")
        output.write_line("  [bold]s[/] / ctrl+s  Submit answer")
        output.write_line("  [bold]n[/]           Next step")
        output.write_line("  [bold]b[/]           Previous step")
        output.write_line("  [bold]h[/]           Show hint")
        output.write_line("  [bold]w[/] / F2      Save progress")
        output.write_line("  [bold]e[/]           Edit in nvim")
        output.write_line("  [bold]p[/]           Toggle sandbox")
        output.write_line("  [bold]f[/]           Toggle feedback")
        output.write_line("  [bold]q[/]           Quit to home")
        output.write_line("")
        output.write_line("  [bold]F5/F6/F7[/]    Jump to zone 1/2/3")
        output.write_line("  [bold]Esc[/]         Cycle to next zone")
        output.write_line("")

    # ── Chat ──

    async def on_output_pane_chat_submitted(self, event: OutputPane.ChatSubmitted) -> None:
        """Handle a chat question from the input line."""
        output = self.query_one(OutputPane)
        output.write_line(f"[bold #E25A1C]You:[/] {event.question}")

        lesson_title = ""
        step_context = ""
        if self.runner and self.runner.state:
            lesson_title = self.runner.state.lesson.title
            step = self.runner.current_step()
            if step:
                step_context = step.output

        code_context = self.query_one(CodeEditor).code

        output.write_line("[dim]Thinking...[/]")
        answer = await self.evaluator.chat(
            question=event.question,
            lesson_title=lesson_title,
            step_context=step_context,
            code_context=code_context,
            depth=self.depth.value,
        )
        output.write_line(f"[bold #FF6F00]Tutor:[/] {answer}")

    # ── Editor callback ──

    def on_code_editor_code_updated(self, event: CodeEditor.CodeUpdated) -> None:
        """Handle code updated from external editor."""
        output = self.query_one(OutputPane)
        output.write_line("[dim]Code updated from editor.[/]")

    # ── Lesson navigation ──

    def _advance_to_next_lesson(self) -> None:
        """Move to the next lesson in the course."""
        next_idx = self._current_lesson_idx + 1
        if next_idx < len(self.course.lessons):
            output = self.query_one(OutputPane)
            output.write_line(f"\n[green bold]Lesson complete! Moving to next lesson...[/]")
            self._start_lesson(next_idx)
        else:
            self._show_course_complete()

    def _show_course_complete(self) -> None:
        lesson_pane = self.query_one(LessonPane)
        lesson_pane.set_content(
            "# Course Complete!\n\n"
            f"Congratulations! You've finished **{self.course.title}**.\n\n"
            "Press **q** in the controls pane to return to the home screen."
        )
