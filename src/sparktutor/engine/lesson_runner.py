"""Lesson state machine: load → present → evaluate → advance."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from sparktutor.engine.adaptive import Depth, LearnerProfile
from sparktutor.engine.evaluator import EvalResult, Evaluator
from sparktutor.engine.executor import ExecResult, Executor
from sparktutor.engine.feedback import parse_stderr
from sparktutor.engine.lesson_loader import Lesson, Step, load_lesson
from sparktutor.state.progress import ProgressStore


class StepState(str, Enum):
    PRESENTING = "presenting"  # Showing content/question to user
    AWAITING_INPUT = "awaiting_input"  # Waiting for user code/answer
    EVALUATING = "evaluating"  # Running evaluation
    FEEDBACK = "feedback"  # Showing feedback
    COMPLETE = "complete"  # Step passed, ready for next


@dataclass
class RunnerState:
    lesson: Lesson
    filtered_steps: list[Step]
    current_index: int = 0
    step_state: StepState = StepState.PRESENTING
    attempts: int = 0
    last_result: Optional[EvalResult] = None
    last_exec: Optional[ExecResult] = None

    @property
    def current_step(self) -> Optional[Step]:
        if 0 <= self.current_index < len(self.filtered_steps):
            return self.filtered_steps[self.current_index]
        return None

    @property
    def is_finished(self) -> bool:
        return self.current_index >= len(self.filtered_steps)

    @property
    def progress_fraction(self) -> float:
        total = len(self.filtered_steps)
        if total == 0:
            return 1.0
        return self.current_index / total


class LessonRunner:
    """Drives lesson progression, evaluation, and state persistence."""

    def __init__(
        self,
        course_id: str,
        executor: Executor,
        evaluator: Evaluator,
        progress: Optional[ProgressStore] = None,
        profile: Optional[LearnerProfile] = None,
    ):
        self.course_id = course_id
        self.executor = executor
        self.evaluator = evaluator
        self.progress = progress or ProgressStore()
        self.profile = profile or LearnerProfile()
        self.state: Optional[RunnerState] = None

    def load_lesson(self, lesson_dir: Path) -> RunnerState:
        """Load a lesson and filter steps by depth."""
        lesson = load_lesson(lesson_dir)
        depth = self.profile.depth.value
        filtered = lesson.steps_for_depth(depth)

        # Skip meta steps in filtered list (they're metadata)
        filtered = [s for s in filtered if s.cls != "meta"]

        self.state = RunnerState(lesson=lesson, filtered_steps=filtered)

        # Resume from saved progress
        saved = self.progress.get(self.course_id, lesson.id)
        if saved and not saved.completed:
            self.state.current_index = min(saved.current_step, len(filtered) - 1)
            self._restored_code = saved.last_code
        else:
            self._restored_code = ""

        return self.state

    def get_restored_code(self) -> str:
        """Return saved code from previous session (empty if none)."""
        code = getattr(self, "_restored_code", "")
        self._restored_code = ""  # Only return once
        return code

    def current_step(self) -> Optional[Step]:
        if self.state is None:
            return None
        return self.state.current_step

    async def submit(self, user_input: str) -> EvalResult:
        """Submit user answer/code for the current step."""
        if self.state is None or self.state.current_step is None:
            return EvalResult(passed=False, feedback=[])

        step = self.state.current_step
        self.state.step_state = StepState.EVALUATING
        self.state.attempts += 1

        # Execute if needed
        exec_result = None
        if step.requires_execution and step.cls in ("script", "cmd_question"):
            exec_result = await self.executor.execute(user_input)
            self.state.last_exec = exec_result

            # Parse stderr for additional feedback
            if exec_result.stderr:
                stderr_feedback = parse_stderr(exec_result.stderr)

        # Evaluate
        result = await self.evaluator.evaluate(
            code=user_input,
            step=step,
            depth=self.profile.depth.value,
            exec_result=exec_result,
            lesson_title=self.state.lesson.title,
        )

        # Merge execution feedback
        if exec_result and exec_result.stderr:
            stderr_items = parse_stderr(exec_result.stderr)
            result.feedback.extend(stderr_items)

        self.state.last_result = result
        self.state.step_state = StepState.FEEDBACK

        # Track signals
        self.profile.record_attempt(
            passed=result.passed,
            used_hint=False,
            signals=result.skill_signals,
        )

        # Save progress
        self._save_progress(user_input)

        return result

    def advance(self, current_code: str = "") -> Optional[Step]:
        """Move to the next step (only if current step passed)."""
        if self.state is None:
            return None

        self.state.current_index += 1
        self.state.attempts = 0
        self.state.step_state = StepState.PRESENTING
        self.state.last_result = None
        self.state.last_exec = None

        self._save_progress(current_code)

        return self.state.current_step

    def go_back(self, current_code: str = "") -> Optional[Step]:
        """Move to the previous step."""
        if self.state is None:
            return None
        if self.state.current_index <= 0:
            return None

        self.state.current_index -= 1
        self.state.attempts = 0
        self.state.step_state = StepState.PRESENTING
        self.state.last_result = None
        self.state.last_exec = None

        self._save_progress(current_code)

        return self.state.current_step

    def _save_progress(self, last_code: str) -> None:
        if self.state is None:
            return
        self.progress.save(
            course_id=self.course_id,
            lesson_id=self.state.lesson.id,
            current_step=self.state.current_index,
            total_steps=len(self.state.filtered_steps),
            completed=self.state.is_finished,
            depth=self.profile.depth.value,
            last_code=last_code,
        )

    def get_hint(self) -> Optional[str]:
        """Return the hint for the current step, if available."""
        step = self.current_step()
        if step and step.hint:
            self.profile.record_attempt(passed=False, used_hint=True)
            return step.hint
        return None

    def get_starter_code(self) -> str:
        """Return starter code for the current step.

        If a step has an explicit starter file, use that. Otherwise, generate
        depth-appropriate scaffolding so the student knows where to start.
        """
        step = self.current_step()
        if step is None:
            return ""

        # Use explicit starter file if available
        if step.starter_code and self.state:
            starter_path = self.state.lesson.base_path / step.starter_code
            if starter_path.exists():
                return starter_path.read_text()

        # Generate scaffolding for code steps without an explicit starter
        if step.cls in ("cmd_question", "script"):
            from sparktutor.engine.scaffolding import generate_scaffold

            return generate_scaffold(
                step_output=step.output,
                step_cls=step.cls,
                depth=self.profile.depth.value,
                correct_answer=step.correct_answer or "",
                hint=step.hint or "",
                lesson_title=self.state.lesson.title if self.state else "",
            )

        return ""
