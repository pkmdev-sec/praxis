"""
PRAXIS — high-level allocation convenience.

Most adapters do the same dance: score a prompt, build the thinking config,
emit an ``alloc`` receipt. :func:`allocate_for_model` does all three in one
call and returns a structured result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .allocator import (
    BUDGET_TIERS,
    EFFORT_TIERS,
    TIER_FOR_SCORE,
    build_thinking_config,
    classify_model_family,
)
from .complexity import score_complexity
from .keywords import detect_thinking_keyword, keyword_score
from .receipt import (
    emit_record,
    next_turn_id,
    resolve_session_id,
)

__all__ = ["Allocation", "allocate_for_model"]


@dataclass
class Allocation:
    """A single Praxis decision, including its thinking-config and identity."""

    prompt_preview: str
    prompt_len: int
    complexity: int
    tier: str
    effort: Optional[str]
    tokens: int
    model: str
    model_family: str
    thinking_config: dict
    session_id: str
    turn_id: int
    decision: str = "auto_scored"
    extras: dict = field(default_factory=dict)

    def as_payload(self) -> dict:
        """Payload shape used inside the signed ``alloc`` receipt."""
        return {
            "prompt_preview": self.prompt_preview,
            "prompt_len": self.prompt_len,
            "complexity": self.complexity,
            "tier": self.tier,
            "budget_requested": self.tokens,
            "effort": self.effort,
            "model": self.model,
            "model_family": self.model_family,
            "decision": self.decision,
            **self.extras,
        }


def allocate_for_model(
    prompt: Optional[str],
    model: str,
    *,
    session: Optional[dict] = None,
    emit: bool = True,
    decision: str = "auto_scored",
    extras: Optional[dict] = None,
) -> Allocation:
    """
    Score a prompt, produce the thinking config, and optionally emit a
    signed ``alloc`` receipt. Every adapter in :mod:`praxis.adapters` is a
    thin wrapper around this.

    Passing ``emit=False`` is useful for dry-run / test scenarios where the
    caller wants the decision without side effects.
    """
    prompt = prompt or ""

    # User-typed thinking keywords override the scorer — honouring intent beats
    # any heuristic. The receipt records this as ``decision="keyword_override"``.
    keyword_tokens = detect_thinking_keyword(prompt)
    if keyword_tokens is not None:
        complexity = keyword_score(keyword_tokens) or 5
        decision = "keyword_override"
    else:
        complexity = score_complexity(prompt)

    family = classify_model_family(model)
    thinking = build_thinking_config(complexity, family)

    session_id = resolve_session_id(session or {})
    turn_id = next_turn_id(session_id) if emit else 0

    alloc = Allocation(
        prompt_preview=prompt[:80],
        prompt_len=len(prompt),
        complexity=complexity,
        tier=TIER_FOR_SCORE[complexity],
        effort=EFFORT_TIERS[complexity],
        tokens=BUDGET_TIERS[complexity],
        model=model,
        model_family=family,
        thinking_config=thinking,
        session_id=session_id,
        turn_id=turn_id,
        decision=decision,
        extras=extras or {},
    )

    if emit:
        emit_record(
            ledger_name="allocation-log.jsonl",
            record_type="alloc",
            session_id=session_id,
            turn_id=turn_id,
            payload=alloc.as_payload(),
        )

    return alloc
