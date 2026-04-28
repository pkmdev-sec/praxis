"""
PRAXIS — Escalation primitive.

When a model hits ``stop_reason = max_tokens`` on a ``heavy``-tier turn, the
budget was too small. Escalation retries one tier higher, bounded by
``TierPolicy.max_escalation_hops``. Every hop writes a signed
``escalation`` receipt linking back to the original turn, so the ledger
records the full capability-extraction chain.

Contract:
  - Original allocation already emitted an ``alloc`` receipt (tid=T).
  - The primary model call completed; caller hands us the response.
  - If ``stop_reason=max_tokens`` and the tier is escalatable, we:
      1. Emit ``outcome`` for tid=T (the one that hit the ceiling).
      2. Allocate again at the next tier, **same prompt**, tid=T+1,
         payload tagged with ``escalated_from=T`` + ``hop=1``.
      3. Caller re-dispatches the model with the new thinking_config.
      4. Repeat until hops are exhausted or ``stop_reason != max_tokens``.

This module owns the *bookkeeping*. The caller owns the *dispatch* — we
don't want to hide SDK calls inside Praxis. Adapters use
:func:`should_escalate` + :func:`escalate` in a loop::

    alloc = allocate_for_model(prompt, model, session=sess)
    while True:
        resp = llm.invoke(..., **translate(alloc.thinking_config))
        emit_outcome(alloc.session_id, alloc.turn_id, usage_source=resp, ...)
        if not should_escalate(alloc, resp, policy):
            return resp
        alloc = escalate(alloc, prompt, model, session=sess)
"""

from __future__ import annotations

from typing import Any, Optional

from .allocation import Allocation
from .allocator import TIER_FOR_SCORE
from .policy import Policy, DEFAULT_POLICY
from .receipt import emit_record

__all__ = ["should_escalate", "escalate", "TIER_LADDER"]


# The tier ladder used by :func:`escalate`. Indices advance by one on each
# hop. ``max`` has no successor — escalation stops.
TIER_LADDER = ["none", "light", "medium", "heavy", "max"]


def _extract_stop_reason(response: Any) -> Optional[str]:
    """Best-effort stop_reason extraction across SDK shapes."""
    for attr in ("stop_reason", "finish_reason"):
        v = getattr(response, attr, None)
        if isinstance(v, str):
            return v
    meta = getattr(response, "response_metadata", None) or {}
    for key in ("stop_reason", "finish_reason"):
        v = meta.get(key) if isinstance(meta, dict) else None
        if isinstance(v, str):
            return v
    if isinstance(response, dict):
        return response.get("stop_reason") or response.get("finish_reason")
    return None


def _next_tier(tier: str) -> Optional[str]:
    """Return the next tier up, or None if already at the ceiling."""
    try:
        idx = TIER_LADDER.index(tier)
    except ValueError:
        return None
    if idx >= len(TIER_LADDER) - 1:
        return None
    return TIER_LADDER[idx + 1]


def _tier_score_ceiling(tier: str) -> int:
    """Highest complexity score that maps to this tier (for the escalated alloc).

    Escalation lands at the *ceiling* of the target tier: the user asked for
    more compute, so we give them the hardest effort the tier offers. The
    ``max`` tier returns 10 (full effort='max'), not 9 (effort='xhigh').
    """
    best = None
    for score, t in TIER_FOR_SCORE.items():
        if t == tier:
            best = score if best is None else max(best, score)
    return best or 5


def should_escalate(
    alloc: Allocation,
    response: Any,
    policy: Policy = DEFAULT_POLICY,
    *,
    current_hop: int = 0,
) -> bool:
    """
    Decide whether to retry at a higher tier.

    Returns True iff:
      - The response's stop_reason is ``max_tokens``.
      - The policy for this tier has ``escalate=True``.
      - We haven't exhausted ``max_escalation_hops``.
      - A higher tier exists (``max`` has no successor).
    """
    if _extract_stop_reason(response) != "max_tokens":
        return False
    tier_policy = policy.for_tier(alloc.tier)
    if not tier_policy.escalate:
        return False
    if current_hop >= tier_policy.max_escalation_hops:
        return False
    return _next_tier(alloc.tier) is not None


def escalate(
    alloc: Allocation,
    prompt: str,
    model: str,
    *,
    session: Optional[dict] = None,
    current_hop: int = 0,
) -> Allocation:
    """
    Re-allocate one tier higher, emitting signed receipts at the *target*
    tier (not the scorer's natural output for this prompt).

    The escalated allocation is a full :class:`Allocation` in its own right —
    its own tid, its own thinking_config, its own outcome on the next turn.
    The link back to the original is preserved in ``extras.escalated_from``
    and in the paired ``escalation`` receipt.
    """
    next_tier = _next_tier(alloc.tier)
    if next_tier is None:
        return alloc  # ceiling; nothing to escalate to

    from .allocator import BUDGET_TIERS, EFFORT_TIERS, build_thinking_config, classify_model_family
    from .receipt import next_turn_id, resolve_session_id

    # Build the escalated allocation directly at the target tier. We do NOT
    # re-score the prompt — the caller has *decided* to spend more compute,
    # so the receipt must reflect that decision, not the scorer's opinion.
    forced_score = _tier_score_ceiling(next_tier)
    family = classify_model_family(model)
    session_id = resolve_session_id(session or {"session_id": alloc.session_id})
    turn_id = next_turn_id(session_id)

    escalated = Allocation(
        prompt_preview=prompt[:80],
        prompt_len=len(prompt),
        complexity=forced_score,
        tier=next_tier,
        effort=EFFORT_TIERS[forced_score],
        tokens=BUDGET_TIERS[forced_score],
        model=model,
        model_family=family,
        thinking_config=build_thinking_config(forced_score, family),
        session_id=session_id,
        turn_id=turn_id,
        decision="escalated",
        extras={
            "escalated_from": alloc.turn_id,
            "escalation_hop": current_hop + 1,
            "original_tier": alloc.tier,
        },
    )

    # Emit the ``alloc`` receipt for this escalated turn — with the correct
    # tier/effort, so the ledger doesn't lie about what actually ran.
    emit_record(
        ledger_name="allocation-log.jsonl",
        record_type="alloc",
        session_id=session_id,
        turn_id=turn_id,
        payload=escalated.as_payload(),
    )

    # And the paired ``escalation`` link record for tree-view analysis.
    emit_record(
        ledger_name="escalation-log.jsonl",
        record_type="escalation",
        session_id=session_id,
        turn_id=turn_id,
        payload={
            "escalated_from": alloc.turn_id,
            "from_tier": alloc.tier,
            "to_tier": next_tier,
            "hop": current_hop + 1,
        },
    )
    return escalated
