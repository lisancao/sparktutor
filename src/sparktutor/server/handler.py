"""Server handler: dispatches JSON-lines requests to engine components."""

from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Optional

from sparktutor.config.settings import Settings
from sparktutor.courses.registry import CourseRegistry
from sparktutor.engine.adaptive import Depth, LearnerProfile
from sparktutor.engine.evaluator import Evaluator
from sparktutor.engine.executor import Executor
from sparktutor.engine.lesson_runner import LessonRunner
from sparktutor.state.progress import ProgressStore

from .protocol import Notification


def _step_to_dict(step) -> dict:
    """Serialize a Step dataclass to a JSON-friendly dict."""
    if step is None:
        return {}
    return {
        "cls": step.cls,
        "depth": step.depth,
        "output": step.output,
        "answerChoices": step.answer_choices,
        "correctAnswer": step.correct_answer,
        "hint": step.hint,
        "starterCode": step.starter_code,
        "solutionCode": step.solution_code,
        "requiresExecution": step.requires_execution,
        "lessonTitle": step.lesson_title,
        "estimatedMinutes": step.estimated_minutes,
        "validation": [
            {"type": v.type, "params": v.params} for v in step.validation
        ],
    }


def _feedback_to_dict(item) -> dict:
    return {
        "line": item.line,
        "severity": item.severity,
        "message": item.message,
        "suggestion": item.suggestion,
        "category": getattr(item, "category", None),
    }


class ServerHandler:
    """Routes incoming requests to engine methods and returns result dicts."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        write_notification: Optional[Callable[[Notification], None]] = None,
    ):
        self.settings = settings or Settings.load()
        self._write_notification = write_notification or (lambda n: None)

        self.registry = CourseRegistry()
        self.progress = ProgressStore(
            db_path=self.settings.data_dir / "progress.db"
        )
        self.executor = Executor(settings=self.settings)
        self.evaluator = Evaluator(settings=self.settings)

        self._runner: Optional[LessonRunner] = None
        self._profile = LearnerProfile()
        self._current_course_id: Optional[str] = None

    async def dispatch(self, msg: dict) -> dict:
        """Route a request message to the appropriate handler method."""
        method = msg.get("method", "")
        params = msg.get("params", {})

        handler_map = {
            "listCourses": self._list_courses,
            "getCourseProgress": self._get_course_progress,
            "loadLesson": self._load_lesson,
            "getStep": self._get_step,
            "run": self._run,
            "submit": self._submit,
            "advance": self._advance,
            "goBack": self._go_back,
            "getHint": self._get_hint,
            "chat": self._chat,
            "detectMode": self._detect_mode,
            "resetLesson": self._reset_lesson,
            "getSolution": self._get_solution,
        }

        handler = handler_map.get(method)
        if handler is None:
            raise ValueError(f"Unknown method: {method}")

        return await handler(params)

    async def _list_courses(self, params: dict) -> dict:
        courses = self.registry.list_courses()
        return {
            "courses": [
                {
                    "id": c.id,
                    "title": c.title,
                    "description": c.description,
                    "lessonCount": len(c.lessons),
                    "requiresLakehouse": c.requires_lakehouse,
                    "lessons": c.lessons,
                }
                for c in courses
            ]
        }

    async def _get_course_progress(self, params: dict) -> dict:
        course_id = params["courseId"]
        course = self.registry.get_course(course_id)
        if course is None:
            raise ValueError(f"Unknown course: {course_id}")
        summary = self.progress.get_course_summary(course_id, course.lessons)
        return summary

    async def _load_lesson(self, params: dict) -> dict:
        course_id = params["courseId"]
        lesson_idx = params["lessonIdx"]
        depth = params.get("depth", self._profile.depth.value)

        course = self.registry.get_course(course_id)
        if course is None:
            raise ValueError(f"Unknown course: {course_id}")
        if lesson_idx < 0 or lesson_idx >= len(course.lessons):
            raise ValueError(f"Lesson index {lesson_idx} out of range")

        lesson_id = course.lessons[lesson_idx]
        lesson_dir = self.registry.courses_dir / course_id / "lessons" / lesson_id

        self._profile.depth = Depth(depth)
        self._current_course_id = course_id
        self._runner = LessonRunner(
            course_id=course_id,
            executor=self.executor,
            evaluator=self.evaluator,
            progress=self.progress,
            profile=self._profile,
        )
        state = self._runner.load_lesson(lesson_dir)

        step = state.current_step
        restored_code = self._runner.get_restored_code()
        starter_code = self._runner.get_starter_code()

        return {
            "step": _step_to_dict(step),
            "currentIndex": state.current_index,
            "totalSteps": len(state.filtered_steps),
            "lessonTitle": state.lesson.title,
            "lessonId": state.lesson.id,
            "restoredCode": restored_code,
            "starterCode": starter_code,
        }

    async def _get_step(self, params: dict) -> dict:
        if self._runner is None or self._runner.state is None:
            raise ValueError("No lesson loaded")

        state = self._runner.state
        step = state.current_step
        starter_code = self._runner.get_starter_code()

        return {
            "step": _step_to_dict(step),
            "currentIndex": state.current_index,
            "totalSteps": len(state.filtered_steps),
            "starterCode": starter_code,
        }

    async def _run(self, params: dict) -> dict:
        code = params["code"]

        def on_output(line: str):
            self._write_notification(
                Notification("output", {"line": line})
            )

        result = await self.executor.execute(code, on_output=on_output)
        return {
            "exitCode": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "mode": result.mode.value,
        }

    async def _submit(self, params: dict) -> dict:
        if self._runner is None:
            raise ValueError("No lesson loaded")

        code = params["code"]
        result = await self._runner.submit(code)
        return {
            "passed": result.passed,
            "feedback": [_feedback_to_dict(f) for f in result.feedback],
            "encouragement": result.encouragement,
            "skillSignals": result.skill_signals,
        }

    async def _advance(self, params: dict) -> dict:
        if self._runner is None:
            raise ValueError("No lesson loaded")

        step = self._runner.advance(current_code=params.get("code", ""))
        if self._runner.state and self._runner.state.is_finished:
            return {"finished": True}

        starter_code = self._runner.get_starter_code()
        return {
            "finished": False,
            "step": _step_to_dict(step),
            "currentIndex": self._runner.state.current_index if self._runner.state else 0,
            "totalSteps": len(self._runner.state.filtered_steps) if self._runner.state else 0,
            "starterCode": starter_code,
        }

    async def _go_back(self, params: dict) -> dict:
        if self._runner is None:
            raise ValueError("No lesson loaded")

        step = self._runner.go_back(current_code=params.get("code", ""))
        if step is None:
            return {"atStart": True}

        starter_code = self._runner.get_starter_code()
        return {
            "atStart": False,
            "step": _step_to_dict(step),
            "currentIndex": self._runner.state.current_index if self._runner.state else 0,
            "totalSteps": len(self._runner.state.filtered_steps) if self._runner.state else 0,
            "starterCode": starter_code,
        }

    async def _get_hint(self, params: dict) -> dict:
        if self._runner is None:
            raise ValueError("No lesson loaded")

        hint = self._runner.get_hint()
        return {"hint": hint or "No hint available for this step."}

    async def _chat(self, params: dict) -> dict:
        question = params["question"]

        step_context = ""
        code_context = params.get("code", "")
        lesson_title = ""
        extra_context = ""

        if self._runner and self._runner.state:
            lesson_title = self._runner.state.lesson.title
            step = self._runner.state.current_step
            if step:
                step_context = step.output

            # Include last execution output so the tutor can reference it
            last_exec = self._runner.state.last_exec
            if last_exec:
                parts = []
                if last_exec.stdout:
                    parts.append(f"Last execution stdout:\n{last_exec.stdout[:2000]}")
                if last_exec.stderr:
                    parts.append(f"Last execution stderr:\n{last_exec.stderr[:2000]}")
                if parts:
                    extra_context += "\n".join(parts)

            # Include last feedback so the tutor knows what was already said
            last_result = self._runner.state.last_result
            if last_result and last_result.feedback:
                fb_lines = []
                for fb in last_result.feedback[:10]:
                    cat = f"[{fb.category}] " if getattr(fb, "category", None) else ""
                    fb_lines.append(f"  {cat}{fb.message}")
                extra_context += "\nPrior feedback:\n" + "\n".join(fb_lines)

        answer = await self.evaluator.chat(
            question=question,
            lesson_title=lesson_title,
            step_context=step_context,
            code_context=code_context,
            depth=self._profile.depth.value,
            extra_context=extra_context,
        )
        return {"answer": answer}

    async def _get_solution(self, params: dict) -> dict:
        if self._runner is None or self._runner.state is None:
            raise ValueError("No lesson loaded")

        step = self._runner.state.current_step
        if step is None or not step.solution_code:
            return {"solution": ""}

        solution_path = self._runner.state.lesson.base_path / step.solution_code
        if solution_path.exists():
            return {"solution": solution_path.read_text()}
        return {"solution": ""}

    async def _reset_lesson(self, params: dict) -> dict:
        course_id = params["courseId"]
        lesson_id = params["lessonId"]
        self.progress.reset_lesson(course_id, lesson_id)
        # Clear the runner so the lesson reloads fresh
        self._runner = None
        return {"ok": True}

    async def _detect_mode(self, params: dict) -> dict:
        mode = await self.executor.detect_mode()
        return {"mode": mode.value}
