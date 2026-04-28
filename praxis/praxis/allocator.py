"""
PRAXIS — Tier + model-family → thinking config.

Mirrors ``lib/effort-mapper.mjs``. Two invariants:

  1. Same score + same model → same thinking config on every platform.
  2. The config uses the *correct* Anthropic shape per model family —
     adaptive for Opus 4.7+, adaptive+legacy for Opus 4.6 / Sonnet 4.6,
     manual ``budget_tokens`` for Opus 4.5 and earlier. Getting this
     wrong produces 400s on Opus 4.7; getting it right is the whole point.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

__all__ = [
    "EFFORT_TIERS",
    "BUDGET_TIERS",
    "TIER_FOR_SCORE",
    "DEFAULT_MODEL",
    "allocate",
    "build_thinking_config",
    "classify_model_family",
]

EFFORT_TIERS = {
    1: None, 2: None,
    3: "low", 4: "low",
    5: "medium", 6: "medium",
    7: "high", 8: "high",
    9: "xhigh", 10: "max",
}

BUDGET_TIERS = {
    1: 0, 2: 0,
    3: 2048, 4: 2048,
    5: 8192, 6: 8192,
    7: 16384, 8: 16384,
    9: 32768, 10: 32768,
}

TIER_FOR_SCORE = {
    1: "none", 2: "none",
    3: "light", 4: "light",
    5: "medium", 6: "medium",
    7: "heavy", 8: "heavy",
    9: "max", 10: "max",
}

DEFAULT_MODEL = "claude-sonnet-4-6"

ModelFamily = Literal["adaptive_only", "adaptive_preferred", "manual"]

# Order matters: most specific patterns first. Keep in sync with
# lib/effort-mapper.mjs::MODEL_FAMILY_PATTERNS.
_MODEL_FAMILIES = [
    (re.compile(r"^claude-mythos", re.IGNORECASE), "adaptive_only"),
    (re.compile(r"^claude-opus-4-7", re.IGNORECASE), "adaptive_only"),
    (re.compile(r"^claude-opus-4-6", re.IGNORECASE), "adaptive_preferred"),
    (re.compile(r"^claude-sonnet-4-6", re.IGNORECASE), "adaptive_preferred"),
    (re.compile(r"^claude-haiku-4-5", re.IGNORECASE), "manual"),
    (
        re.compile(
            r"^claude-(opus-4-5|opus-4-1|opus-4\b|sonnet-4-5|sonnet-4\b|haiku-4|sonnet-3-7)",
            re.IGNORECASE,
        ),
        "manual",
    ),
]


def _clamp_score(score) -> int:
    try:
        n = round(float(score))
    except (TypeError, ValueError):
        n = 1
    return max(1, min(10, int(n)))


def classify_model_family(model: Optional[str]) -> ModelFamily:
    """
    Classify a model name into one of ``adaptive_only``, ``adaptive_preferred``,
    ``manual``. Unknown models default to ``adaptive_only`` — safer than
    emitting deprecated fields to a future model.
    """
    if not isinstance(model, str) or not model.strip():
        return "adaptive_only"
    for pattern, family in _MODEL_FAMILIES:
        if pattern.search(model):
            return family
    return "adaptive_only"


def allocate(complexity: int, model: str = DEFAULT_MODEL) -> dict:
    """Return ``{"tokens", "tier", "effort", "model", "model_family"}``."""
    score = _clamp_score(complexity)
    return {
        "tokens": BUDGET_TIERS[score],
        "tier": TIER_FOR_SCORE[score],
        "effort": EFFORT_TIERS[score],
        "model": model,
        "model_family": classify_model_family(model),
    }


def build_thinking_config(complexity: int, family: ModelFamily) -> dict:
    """
    Produce the Anthropic-request-shape dict for (score, family).

    ``adaptive_only`` returns ``{}`` when thinking should be skipped — the
    caller must simply omit the field from the outgoing request. Emitting
    ``thinking: {"type": "disabled"}`` on Opus 4.7 is accepted but wasteful.
    """
    score = _clamp_score(complexity)
    effort = EFFORT_TIERS[score]
    tokens = BUDGET_TIERS[score]

    if family == "adaptive_only":
        if effort is None:
            return {}
        return {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort},
        }

    if family == "adaptive_preferred":
        if effort is None:
            return {"thinking": {"type": "disabled"}}
        return {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort},
            "legacy_budget_tokens": tokens,
        }

    # manual
    if tokens == 0:
        return {"thinking": {"type": "disabled"}}
    return {"thinking": {"type": "enabled", "budget_tokens": tokens}}
