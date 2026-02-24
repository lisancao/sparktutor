"""Tests for the ServerHandler dispatch layer."""

from __future__ import annotations

import pytest

from sparktutor.config.settings import Settings
from sparktutor.courses.registry import CourseRegistry
from sparktutor.server.handler import ServerHandler
from sparktutor.server.protocol import Notification
from sparktutor.state.progress import ProgressStore


@pytest.fixture
def handler(sample_course_dir, tmp_path):
    """Create a ServerHandler backed by the sample course directory."""
    settings = Settings(data_dir=tmp_path / "data")
    settings.execution_mode = settings.execution_mode  # keep auto

    notifications: list[Notification] = []

    h = ServerHandler(
        settings=settings,
        write_notification=lambda n: notifications.append(n),
    )
    # Override registry to point at our test course directory
    h.registry = CourseRegistry(courses_dir=sample_course_dir.parent)
    # Override progress to use tmp db
    h.progress = ProgressStore(db_path=tmp_path / "data" / "test_progress.db")
    h._notifications = notifications
    return h


class TestListCourses:
    @pytest.mark.asyncio
    async def test_returns_courses(self, handler):
        result = await handler.dispatch({"method": "listCourses", "params": {}})
        assert "courses" in result
        courses = result["courses"]
        assert len(courses) == 1
        assert courses[0]["id"] == "test_course"
        assert courses[0]["title"] == "Test Course"
        assert courses[0]["lessonCount"] == 1

    @pytest.mark.asyncio
    async def test_unknown_method(self, handler):
        with pytest.raises(ValueError, match="Unknown method"):
            await handler.dispatch({"method": "nonExistent", "params": {}})


class TestGetCourseProgress:
    @pytest.mark.asyncio
    async def test_no_progress(self, handler):
        result = await handler.dispatch({
            "method": "getCourseProgress",
            "params": {"courseId": "test_course"},
        })
        assert result["started"] is False

    @pytest.mark.asyncio
    async def test_unknown_course(self, handler):
        with pytest.raises(ValueError, match="Unknown course"):
            await handler.dispatch({
                "method": "getCourseProgress",
                "params": {"courseId": "nonexistent"},
            })


class TestLoadLesson:
    @pytest.mark.asyncio
    async def test_load_first_lesson(self, handler):
        result = await handler.dispatch({
            "method": "loadLesson",
            "params": {"courseId": "test_course", "lessonIdx": 0},
        })
        assert "step" in result
        assert result["lessonTitle"] == "Test Lesson"
        assert result["totalSteps"] > 0
        assert result["currentIndex"] == 0

    @pytest.mark.asyncio
    async def test_load_with_depth(self, handler):
        result = await handler.dispatch({
            "method": "loadLesson",
            "params": {"courseId": "test_course", "lessonIdx": 0, "depth": "advanced"},
        })
        assert result["totalSteps"] > 0

    @pytest.mark.asyncio
    async def test_invalid_lesson_index(self, handler):
        with pytest.raises(ValueError, match="out of range"):
            await handler.dispatch({
                "method": "loadLesson",
                "params": {"courseId": "test_course", "lessonIdx": 99},
            })


class TestStepNavigation:
    @pytest.mark.asyncio
    async def _load(self, handler):
        """Helper to load a lesson first."""
        await handler.dispatch({
            "method": "loadLesson",
            "params": {"courseId": "test_course", "lessonIdx": 0},
        })

    @pytest.mark.asyncio
    async def test_get_step(self, handler):
        await self._load(handler)
        result = await handler.dispatch({"method": "getStep", "params": {}})
        assert "step" in result
        assert "currentIndex" in result
        assert "totalSteps" in result

    @pytest.mark.asyncio
    async def test_advance(self, handler):
        await self._load(handler)
        result = await handler.dispatch({"method": "advance", "params": {}})
        assert "step" in result or "finished" in result

    @pytest.mark.asyncio
    async def test_go_back_at_start(self, handler):
        await self._load(handler)
        result = await handler.dispatch({"method": "goBack", "params": {}})
        assert result.get("atStart") is True

    @pytest.mark.asyncio
    async def test_get_hint(self, handler):
        await self._load(handler)
        result = await handler.dispatch({"method": "getHint", "params": {}})
        assert "hint" in result


class TestDetectMode:
    @pytest.mark.asyncio
    async def test_detect_mode(self, handler):
        # Force dry run so test doesn't depend on Docker/Spark
        handler.executor._force_dry_run = True
        result = await handler.dispatch({"method": "detectMode", "params": {}})
        assert result["mode"] == "dry_run"


class TestRun:
    @pytest.mark.asyncio
    async def test_run_valid_code(self, handler):
        handler.executor._force_dry_run = True
        result = await handler.dispatch({
            "method": "run",
            "params": {"code": "x = 42"},
        })
        assert result["exitCode"] == 0
        assert result["mode"] == "dry_run"

    @pytest.mark.asyncio
    async def test_run_syntax_error(self, handler):
        handler.executor._force_dry_run = True
        result = await handler.dispatch({
            "method": "run",
            "params": {"code": "def foo("},
        })
        assert result["exitCode"] == 1


class TestSubmit:
    @pytest.mark.asyncio
    async def test_submit_no_lesson(self, handler):
        with pytest.raises(ValueError, match="No lesson loaded"):
            await handler.dispatch({
                "method": "submit",
                "params": {"code": "x = 42"},
            })

    @pytest.mark.asyncio
    async def test_submit_text_step(self, handler):
        # Load lesson, first step is text (no validation needed)
        await handler.dispatch({
            "method": "loadLesson",
            "params": {"courseId": "test_course", "lessonIdx": 0},
        })
        result = await handler.dispatch({
            "method": "submit",
            "params": {"code": "anything"},
        })
        assert "passed" in result
        assert "feedback" in result
