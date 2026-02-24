"""SQLite-backed progress tracking for SparkTutor."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class LessonProgress:
    course_id: str
    lesson_id: str
    current_step: int
    total_steps: int
    completed: bool
    depth: str
    last_code: str
    updated_at: str


class ProgressStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (Path.home() / ".sparktutor" / "progress.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS progress (
                    course_id TEXT NOT NULL,
                    lesson_id TEXT NOT NULL,
                    current_step INTEGER DEFAULT 0,
                    total_steps INTEGER DEFAULT 0,
                    completed INTEGER DEFAULT 0,
                    depth TEXT DEFAULT 'beginner',
                    last_code TEXT DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (course_id, lesson_id)
                )
            """)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def get(self, course_id: str, lesson_id: str) -> Optional[LessonProgress]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM progress WHERE course_id = ? AND lesson_id = ?",
                (course_id, lesson_id),
            ).fetchone()
        if not row:
            return None
        return LessonProgress(
            course_id=row[0],
            lesson_id=row[1],
            current_step=row[2],
            total_steps=row[3],
            completed=bool(row[4]),
            depth=row[5],
            last_code=row[6],
            updated_at=row[7],
        )

    def save(
        self,
        course_id: str,
        lesson_id: str,
        current_step: int,
        total_steps: int,
        completed: bool = False,
        depth: str = "beginner",
        last_code: str = "",
    ) -> None:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO progress
                   (course_id, lesson_id, current_step, total_steps, completed, depth, last_code, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (course_id, lesson_id, current_step, total_steps, int(completed), depth, last_code, now),
            )

    def get_course_progress(self, course_id: str) -> list[LessonProgress]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM progress WHERE course_id = ? ORDER BY lesson_id",
                (course_id,),
            ).fetchall()
        return [
            LessonProgress(
                course_id=r[0], lesson_id=r[1], current_step=r[2],
                total_steps=r[3], completed=bool(r[4]), depth=r[5],
                last_code=r[6], updated_at=r[7],
            )
            for r in rows
        ]

    def get_course_summary(self, course_id: str, lesson_ids: list[str]) -> dict:
        """Return a summary of course progress for the home screen.

        Returns dict with keys: started, current_lesson_id, current_lesson_idx,
        lessons_completed, total_lessons, depth, updated_at.
        """
        progress_list = self.get_course_progress(course_id)
        if not progress_list:
            return {"started": False}

        progress_map = {p.lesson_id: p for p in progress_list}
        completed = sum(1 for p in progress_list if p.completed)

        # Find the first incomplete lesson (in course order)
        current_lesson_id = None
        current_lesson_idx = 0
        for i, lid in enumerate(lesson_ids):
            p = progress_map.get(lid)
            if p is None or not p.completed:
                current_lesson_id = lid
                current_lesson_idx = i
                break
        else:
            # All completed
            current_lesson_id = lesson_ids[-1] if lesson_ids else None
            current_lesson_idx = len(lesson_ids) - 1

        # Get the most recent update
        latest = max(progress_list, key=lambda p: p.updated_at)

        return {
            "started": True,
            "current_lesson_id": current_lesson_id,
            "current_lesson_idx": current_lesson_idx,
            "lessons_completed": completed,
            "total_lessons": len(lesson_ids),
            "depth": latest.depth,
            "updated_at": latest.updated_at,
        }

    def reset_lesson(self, course_id: str, lesson_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM progress WHERE course_id = ? AND lesson_id = ?",
                (course_id, lesson_id),
            )

    def reset_course(self, course_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM progress WHERE course_id = ?",
                (course_id,),
            )
