"""
PRAXIS — Reflection primitive.

A second pass that reviews the primary answer and either (a) ratifies it or
(b) returns a revised answer. Under the capability-first framing,
reflection is the cheapest reliable way to extract more quality out of a
fixed model: the reviewer catches first-pass errors the writer missed.

Two reflector strategies, selected by :class:`TierPolicy.prefer_droidx_reflector`:

1. **DroidX** (preferred when available) — adversarial challenger running a
   *structurally different* strategy (e.g. symbolic_validate vs plan-execute).
   Gives us a quality attestation *and* a candidate revision.
2. **Self-reflection** (always-available fallback) — re-prompt the same
   model with a "critique your previous answer" template. Works everywhere
   but produces correlated errors (writer and critic share priors).

Receipt schema: every reflection pass emits a ``reflection`` record::

    { "v": 1, "type": "reflection", "sid": ..., "tid": <original_turn>,
      "payload": { "strategy": "droidx" | "self",
                   "verdict": "ratify" | "revise" | "partial" | "unreachable",
                   "revision_provided": bool,
                   "reflector_model": str,
                   "findings_count": int,
                   "duration_ms": int|null }, ... }

The caller provides a ``reflector`` callable: ``(prompt, answer) -> ReflectionResult``.
Praxis owns the receipt; the caller owns the dispatch. This keeps the
module SDK-agnostic — no hard dependency on LangChain, the Anthropic SDK,
or a running DroidX.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .allocation import Allocation
from .receipt import emit_record

__all__ = [
    "ReflectionResult",
    "Reflector",
    "reflect",
    "self_reflect_prompt",
    "DROIDX_STRATEGY",
    "SELF_STRATEGY",
]


DROIDX_STRATEGY = "droidx"
SELF_STRATEGY = "self"


@dataclass
class ReflectionResult:
    """Outcome of one reflection pass."""

    verdict: str                      # "ratify" | "revise" | "partial" | "unreachable"
    revision: Optional[str] = None    # Revised answer if verdict == "revise"
    findings: Optional[list] = None   # Short list of issues found
    reflector_model: Optional[str] = None
    strategy: str = SELF_STRATEGY
    duration_ms: Optional[int] = None


# A reflector is any callable that takes (prompt, answer) and returns a
# :class:`ReflectionResult`. This is an intentionally tiny interface so
# both DroidX and a bare LangChain chain can satisfy it.
Reflector = Callable[[str, str], ReflectionResult]


def self_reflect_prompt(prompt: str, answer: str) -> str:
    """
    Canonical self-reflection template. Returns a single string the caller
    can feed to the same model to produce a critique + revision.

    Kept factored-out so adapters can re-use it without importing the full
    reflection module.
    """
    return (
        "You previously produced an answer to a task. Critically review your "
        "answer for correctness, completeness, and any subtle errors. If the "
        "answer is correct and complete, reply exactly 'RATIFY'. Otherwise, "
        "reply with a revised answer.\n\n"
        f"---\nTASK:\n{prompt}\n\n"
        f"---\nYOUR PREVIOUS ANSWER:\n{answer}\n\n"
        "---\nREVIEW AND REVISE:"
    )


def reflect(
    alloc: Allocation,
    prompt: str,
    answer: str,
    reflector: Reflector,
) -> ReflectionResult:
    """
    Run a reflection pass via ``reflector`` and emit the signed receipt.

    The caller is expected to check :class:`TierPolicy.reflect` before
    calling this — Praxis doesn't second-guess the policy once it's set.
    """
    result = reflector(prompt, answer)

    emit_record(
        ledger_name="reflection-log.jsonl",
        record_type="reflection",
        session_id=alloc.session_id,
        turn_id=alloc.turn_id,
        payload={
            "strategy": result.strategy,
            "verdict": result.verdict,
            "revision_provided": result.revision is not None,
            "reflector_model": result.reflector_model,
            "findings_count": len(result.findings) if result.findings else 0,
            "duration_ms": result.duration_ms,
        },
    )
    return result
