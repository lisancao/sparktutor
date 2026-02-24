"""Answer normalization for comparison."""

from __future__ import annotations

import re


def normalize_text(text: str) -> str:
    """Normalize text for comparison: strip, collapse whitespace, lowercase."""
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def normalize_code(code: str) -> str:
    """Normalize code for comparison: strip, normalize quotes and whitespace."""
    code = code.strip()
    code = re.sub(r'["\']', "'", code)
    code = re.sub(r"\s+", " ", code)
    return code


def normalize_choice(choice: str) -> str:
    """Normalize a multiple-choice answer for comparison."""
    choice = choice.strip()
    choice = re.sub(r"[^a-zA-Z0-9_@.\s]", "", choice)
    return choice.upper()


def choices_match(guess: str, correct: str) -> bool:
    """Check if a multiple-choice guess matches the correct answer."""
    return normalize_choice(guess) == normalize_choice(correct)


def code_match(guess: str, correct: str) -> bool:
    """Check if code guess matches the expected answer (flexible)."""
    return normalize_code(guess) == normalize_code(correct)
