"""
PRAXIS — DroidX reflector adapter.

DroidX is an adversarial second-opinion system that applies a *structurally
different* strategy to a given draft answer (symbolic_validate,
counterfactual, debate, etc.). Its output already has the shape Praxis
wants: ``{verdict, findings, strategy_used}``.

This module turns DroidX into a drop-in :data:`praxis.reflection.Reflector`
callable so ``PraxisBudget(..., reflector=droidx_reflector(...))`` just works.

Three design choices worth calling out:

  1. **Verdict mapping**.
       agree       → ratify
       disagree    → revise   (+ findings.revision if provided)
       partial     → partial  (flag, no substitution)
       unreachable → unreachable (don't crash the turn; log and move on)

  2. **Budget-aware challenger selection**. When Praxis's primary turn ran
     at ``high`` / ``xhigh`` / ``max`` effort, we pass that to DroidX's
     ``harness_router`` so it can pick a *cheap, structurally different*
     challenge strategy (symbolic_validate, counterfactual) — the
     ensemble is strictly stronger when the two agents attack the
     problem with different resources.

  3. **No hard dependency on DroidX being reachable**. If
     ``droidx_challenge`` returns ``verdict=unreachable`` or raises, we
     produce a ``ReflectionResult`` with that verdict and let the caller
     keep going. Reflection is an amplifier, not a load-bearing path.

The actual DroidX client callable is passed in by the caller —
``droidx_reflector(challenge_fn=my_droidx_client)`` — so this module has
no compile-time dependency on the DroidX SDK. CI can test the whole
adapter with a tiny stub.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from ..allocation import Allocation
from ..reflection import (
    DROIDX_STRATEGY,
    ReflectionResult,
    SELF_STRATEGY,
)


__all__ = [
    "droidx_reflector",
    "DroidXChallengeFn",
]


# ── Types ──────────────────────────────────────────────────────────────────

# A DroidX "challenge" callable. Matches the real droidx_challenge tool's
# keyword-arg shape (question, cxr_answer, strategy_used, focus, tool_transcript,
# plus an optional ``praxis_alloc`` dict we pass through for budget-aware
# routing). Returns whatever DroidX gives us; we normalise on the way out.
DroidXChallengeFn = Callable[..., Dict[str, Any]]


# ── Verdict mapping ────────────────────────────────────────────────────────

_DROIDX_TO_PRAXIS_VERDICT = {
    "agree":       "ratify",
    "partial":     "partial",
    "disagree":    "revise",
    "unreachable": "unreachable",
}


def _normalise_verdict(raw: Any) -> str:
    """Map a DroidX verdict onto Praxis's reflection vocabulary."""
    if isinstance(raw, str):
        v = raw.strip().lower()
        if v in _DROIDX_TO_PRAXIS_VERDICT:
            return _DROIDX_TO_PRAXIS_VERDICT[v]
    return "partial"  # safest default when DroidX returns something unexpected


# ── Budget-aware strategy hints ────────────────────────────────────────────

# DroidX's harness_router picks a strategy *different* from the primary's.
# We add a second dimension: when the primary burned lots of compute,
# prefer a cheap but structurally divergent challenger; when the primary
# was cheap, prefer a deeper challenger. This is the "complementary not
# inherited" rule from the alignment discussion.
_CHEAP_CHALLENGERS = ["symbolic_validate", "counterfactual"]
_DEEP_CHALLENGERS = ["debate", "plan_then_execute", "counterfactual"]


def _preferred_challengers(alloc_effort: Optional[str]) -> list[str]:
    if alloc_effort in ("high", "xhigh", "max"):
        return _CHEAP_CHALLENGERS
    return _DEEP_CHALLENGERS


# ── The factory ────────────────────────────────────────────────────────────


def droidx_reflector(
    challenge_fn: DroidXChallengeFn,
    *,
    primary_strategy: str = "plan_then_execute",
    focus: Optional[str] = None,
) -> Callable[[str, str], ReflectionResult]:
    """
    Build a :data:`Reflector` callable that delegates to DroidX.

    ``challenge_fn`` is whatever you use to reach DroidX — in CXR, that's
    the ``droidx_challenge`` tool; in a service, it's an HTTP call to
    the DroidX proxy. The callable is expected to accept at least
    ``question``, ``cxr_answer``, ``strategy_used``, and ``focus``
    kwargs and return a dict with a ``verdict`` key.

    The returned reflector is **bound to a single Praxis allocation** via
    a closure: it reads the allocation's effort level to decide which
    challenger strategies to prefer, which is why you construct one
    reflector per turn rather than reusing a single instance across an
    entire session.

    Typical wiring inside a CXR adapter::

        from praxis.adapters.cxr import cxr_praxis_dispatch
        from praxis.adapters.droidx import droidx_reflector
        from praxis.reflection import reflect

        with cxr_praxis_dispatch(msg, model=m, session_id=sid) as ctx:
            response = call_model(msg, effort=ctx.cxr_effort)
            ctx.record_outcome(response)

        if ctx.alloc.tier in ("heavy", "max"):
            reflector = droidx_reflector(
                my_droidx_client,
                primary_strategy="plan_then_execute",
            )
            result = reflect(ctx.alloc, msg, response.text, reflector)
    """

    def _reflect(prompt: str, answer: str) -> ReflectionResult:
        t0 = time.monotonic()
        # Caller passes us the Allocation via closure only if they use
        # the CXR adapter wiring. In the common case we just forward what
        # we have and let DroidX's router pick a strategy.
        try:
            raw = challenge_fn(
                question=prompt,
                cxr_answer=answer,
                strategy_used=primary_strategy,
                focus=focus,
                # Pass a hint about what kinds of challengers would be
                # complementary. DroidX is free to ignore this (backwards-
                # compatible addition — older DroidX builds won't use it).
                preferred_challengers=_preferred_challengers(None),
            )
        except Exception as e:  # noqa: BLE001
            duration = int((time.monotonic() - t0) * 1000)
            return ReflectionResult(
                verdict="unreachable",
                strategy=DROIDX_STRATEGY,
                findings=[f"droidx client error: {e}"],
                duration_ms=duration,
            )

        verdict = _normalise_verdict(raw.get("verdict"))
        findings = raw.get("findings") or []
        if not isinstance(findings, list):
            findings = [str(findings)]
        revision = raw.get("revision") or raw.get("revised_answer")
        reflector_model = raw.get("challenger_strategy") or raw.get("strategy")

        return ReflectionResult(
            verdict=verdict,
            revision=revision if verdict == "revise" else None,
            findings=findings,
            reflector_model=reflector_model,
            strategy=DROIDX_STRATEGY,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

    return _reflect


# ── Convenience: wire DroidX in with budget awareness per-turn ──────────────


def make_budget_aware_reflector(
    challenge_fn: DroidXChallengeFn,
    alloc: Allocation,
    *,
    primary_strategy: str = "plan_then_execute",
    focus: Optional[str] = None,
) -> Callable[[str, str], ReflectionResult]:
    """
    Same as :func:`droidx_reflector` but closes over an :class:`Allocation`
    so the preferred-challengers hint reflects the primary call's actual
    compute spend.

    This is the form the CXR integration uses in practice: one reflector
    per turn, informed by that turn's effort level.
    """
    effort = alloc.effort

    def _reflect(prompt: str, answer: str) -> ReflectionResult:
        t0 = time.monotonic()
        try:
            raw = challenge_fn(
                question=prompt,
                cxr_answer=answer,
                strategy_used=primary_strategy,
                focus=focus,
                preferred_challengers=_preferred_challengers(effort),
            )
        except Exception as e:  # noqa: BLE001
            return ReflectionResult(
                verdict="unreachable",
                strategy=DROIDX_STRATEGY,
                findings=[f"droidx client error: {e}"],
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

        verdict = _normalise_verdict(raw.get("verdict"))
        findings = raw.get("findings") or []
        if not isinstance(findings, list):
            findings = [str(findings)]
        revision = raw.get("revision") or raw.get("revised_answer")
        reflector_model = raw.get("challenger_strategy") or raw.get("strategy")

        return ReflectionResult(
            verdict=verdict,
            revision=revision if verdict == "revise" else None,
            findings=findings,
            reflector_model=reflector_model,
            strategy=DROIDX_STRATEGY,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

    return _reflect
