"""Adaptive difficulty engine (Zone of Proximal Development).

MVP: Depth is user-declared. This module provides the framework for
future dynamic adjustment based on performance signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Depth(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"

    @classmethod
    def from_choice(cls, choice: int) -> "Depth":
        return {1: cls.BEGINNER, 2: cls.INTERMEDIATE, 3: cls.ADVANCED}.get(
            choice, cls.BEGINNER
        )


@dataclass
class LearnerProfile:
    """Tracks learner signals for adaptive difficulty (post-MVP)."""
    depth: Depth = Depth.BEGINNER
    total_attempts: int = 0
    correct_first_try: int = 0
    hint_usage: int = 0
    skill_signals: list[str] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        if self.total_attempts == 0:
            return 0.0
        return self.correct_first_try / self.total_attempts

    def record_attempt(self, passed: bool, used_hint: bool, signals: list[str] | None = None):
        self.total_attempts += 1
        if passed:
            self.correct_first_try += 1
        if used_hint:
            self.hint_usage += 1
        if signals:
            self.skill_signals.extend(signals)
