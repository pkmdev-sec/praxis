"""
PRAXIS — Complexity scorer.

Rule-based 1-10 scorer. **Canonical algorithm** shared across:

  - ``hooks/praxis-allocator.py`` (Claude Code hook, shipped).
  - ``praxis.complexity`` (this module, Python package).
  - ``lib/complexity-scorer.mjs`` (Node package — see note below).

Algorithm (intentionally simple):

  1. Start at 1.
  2. Take the max tier score from keyword matches (simple/moderate/complex/advanced).
  3. Bump upward for long prompts (>30, >80, >150 words → ≥3, ≥5, ≥7).
  4. Add +1 for multi-code-block or multi-question prompts (structural bonus).
  5. Clamp to [1, 10].

The weighted-blend scorer in ``lib/complexity-scorer.mjs`` (pre-1.2) produced
different numbers than the hook. This module is the single source of truth
going forward — the Node module is now a thin wrapper around the same
algorithm re-expressed in JS. Cross-language receipts require byte-identical
scoring, and the simpler algorithm wins on transparency ("I can reproduce
this number by reading the payload").
"""

from __future__ import annotations

import re
from typing import List, Optional

__all__ = [
    "score_complexity",
    "extract_signals",
    "classify_task_type",
]

_KEYWORD_TIERS = {
    "simple": {
        "score": 1,
        "patterns": [
            r"\bwhat is\b", r"\bdefine\b", r"\bexplain\b", r"\bhow to\b",
            r"\blist\b", r"\bshow me\b", r"\btell me\b", r"\bwhat does\b",
        ],
    },
    "moderate": {
        "score": 4,
        "patterns": [
            r"\bfix\b", r"\bmodify\b", r"\bchange\b", r"\bupdate\b",
            r"\badd\b", r"\bremove\b", r"\brefactor\b", r"\bimplement\b",
            r"\bcreate\b", r"\bwrite\b", r"\bbug\b", r"\berror\b",
        ],
    },
    "complex": {
        "score": 7,
        "patterns": [
            r"\bdesign\b", r"\barchitect\b", r"\bsystem\b", r"\bscalable\b",
            r"\bmigrat", r"\boptimiz", r"\bperformance\b", r"\bsecurity\b",
            r"\bdistributed\b", r"\bmicroservic", r"\bpipeline\b",
        ],
    },
    "advanced": {
        "score": 9,
        "patterns": [
            r"\bdebug\s+complex", r"\brace\s+condition", r"\bmemory\s+leak",
            r"\bconcurrency", r"\bdeadlock", r"\bmulti.?step",
            r"\broot\s+cause", r"\bintermittent", r"\bnondeterministic",
            r"\bcomplex\s+issue", r"\bfull\s+stack",
        ],
    },
}


def _detect_question_type(prompt: str) -> str:
    stripped = prompt.strip()
    if stripped.endswith("?"):
        if re.match(r"^(what|who|where|when|which)\b", prompt, re.IGNORECASE):
            return "factual"
        if re.match(r"^(how|why)\b", prompt, re.IGNORECASE):
            return "explanatory"
        if re.match(r"^(can|could|should|would|is|are|do|does)\b", prompt, re.IGNORECASE):
            return "decisional"
    if re.search(r"\b(implement|create|build|write|add|make)\b", prompt, re.IGNORECASE):
        return "imperative"
    if re.search(r"\b(fix|debug|solve|resolve|troubleshoot)\b", prompt, re.IGNORECASE):
        return "diagnostic"
    if re.search(r"\b(review|check|audit|assess|evaluate)\b", prompt, re.IGNORECASE):
        return "evaluative"
    if re.search(r"\b(design|architect|plan|propose)\b", prompt, re.IGNORECASE):
        return "strategic"
    return "general"


def extract_signals(prompt: Optional[str]) -> dict:
    """Extract descriptive signals about a prompt (does not compute a score)."""
    if not prompt:
        return {
            "keywords": [],
            "length": 0,
            "word_count": 0,
            "question_type": "unknown",
            "matched_tier": None,
        }
    if not isinstance(prompt, str):
        raise TypeError(f"Invalid prompt: expected str, got {type(prompt).__name__}")

    keywords: List[str] = []
    matched_tier: Optional[str] = None
    highest = 0

    for tier, data in _KEYWORD_TIERS.items():
        for pattern in data["patterns"]:
            m = re.search(pattern, prompt, re.IGNORECASE)
            if m:
                keywords.append(m.group(0).lower())
                if data["score"] > highest:
                    highest = data["score"]
                    matched_tier = tier

    word_count = len([w for w in prompt.strip().split() if w])

    return {
        "keywords": list(dict.fromkeys(keywords)),
        "length": len(prompt),
        "word_count": word_count,
        "question_type": _detect_question_type(prompt),
        "matched_tier": matched_tier,
    }


def classify_task_type(prompt: Optional[str]) -> str:
    if not prompt:
        return "question"
    if re.search(r"\b(design|architect|system|scalable|distributed|microservic)", prompt, re.IGNORECASE):
        return "architecture"
    if re.search(r"\b(debug|fix|solve|error|bug|race|deadlock|leak)", prompt, re.IGNORECASE):
        return "debugging"
    if re.search(r"\b(review|check|audit|assess|evaluate)", prompt, re.IGNORECASE):
        return "review"
    if re.search(r"\b(implement|create|build|write|add|refactor|modify)", prompt, re.IGNORECASE):
        return "implementation"
    return "question"


def score_complexity(prompt: Optional[str]) -> int:
    """
    Return the canonical 1-10 complexity score. Byte-identical to the
    ``score_complexity`` function in ``hooks/praxis-allocator.py`` — that
    parity is test-enforced.
    """
    if not prompt or not isinstance(prompt, str):
        return 1

    # Step 1-2: start at 1, take max over keyword-tier scores.
    score = 1
    for tier_data in _KEYWORD_TIERS.values():
        for pattern in tier_data["patterns"]:
            if re.search(pattern, prompt, re.IGNORECASE):
                score = max(score, tier_data["score"])

    # Step 3: length bump.
    word_count = len(prompt.split())
    if word_count > 150:
        score = max(score, 7)
    elif word_count > 80:
        score = max(score, 5)
    elif word_count > 30:
        score = max(score, 3)

    # Step 4: structural bump.
    code_blocks = prompt.count("```") // 2
    question_marks = prompt.count("?")
    if code_blocks > 1 or question_marks > 2:
        score = min(10, score + 1)

    return max(1, min(10, score))
