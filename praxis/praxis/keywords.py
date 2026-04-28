"""
PRAXIS — Thinking keyword detection.

Mirrors ``hooks/praxis-allocator.py::detect_thinking_keyword``. When a user
writes ``ultrathink``, ``megathink``, or ``think step by step`` etc. in the
prompt, the user is telling Praxis to override the scorer. We honor that:
user intent beats rule-based heuristics.
"""

from __future__ import annotations

import re
from typing import Optional

__all__ = [
    "THINKING_KEYWORDS",
    "KEYWORD_TO_SCORE",
    "detect_thinking_keyword",
    "keyword_score",
]

THINKING_KEYWORDS = {
    "ultrathink": 32768,
    "megathink": 16384,
    "think": 8192,
}

# Keyword budget → canonical complexity score for receipt consistency.
KEYWORD_TO_SCORE = {
    32768: 10,
    16384: 8,
    8192: 5,
}

# "think" needs a directive-word qualifier to avoid false positives like
# "I need to think about this" (a statement, not an instruction).
_THINK_DIRECTIVE = re.compile(
    r"\bthink\s+(step\s+by\s+step|carefully|through|deeply|hard|harder|"
    r"critically|systematically|logically)\b",
    re.IGNORECASE,
)


def detect_thinking_keyword(prompt: Optional[str]) -> Optional[int]:
    """Return the keyword's token budget if one is present, else None."""
    if not prompt or not isinstance(prompt, str):
        return None
    lower = prompt.lower()
    if re.search(r"\bultrathink\b", lower):
        return THINKING_KEYWORDS["ultrathink"]
    if re.search(r"\bmegathink\b", lower):
        return THINKING_KEYWORDS["megathink"]
    if _THINK_DIRECTIVE.search(prompt):
        return THINKING_KEYWORDS["think"]
    return None


def keyword_score(tokens: int) -> Optional[int]:
    """Map keyword budget → canonical score, or None if unknown."""
    return KEYWORD_TO_SCORE.get(tokens)
