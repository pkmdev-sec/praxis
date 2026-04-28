"""
PRAXIS — CXR native integration.

CXR is a recursive agent system: every ``spawn_agent`` / ``rlm_query`` /
``rlm_map`` call produces a child turn inside a parent turn, potentially
many levels deep. Praxis needs to:

  1. Allocate per child (different children in the same turn can need
     different budgets).
  2. Preserve the ``parent_tid → child_tid`` link in the ledger so the
     recursion tree is reconstructable for analysis.
  3. Degrade gracefully if Praxis is *off* for a particular call — the
     agent framework must keep working whether the integration is on or off.

The integration is deliberately small: one decorator, one session helper,
one extras builder. CXR itself is unchanged — no vendoring, no fork. The
integration lives in ``praxis`` because the receipt format is ours; CXR
just hands us the right metadata.

Usage from CXR code (pseudo-sketch)::

    from praxis.adapters.cxr import cxr_praxis_dispatch, make_spawn_extras

    def dispatch_spawn(message, *, model, reasoning_effort=None,
                       parent_tid=None, depth=0, spawn_kind="spawn_agent"):
        extras = make_spawn_extras(parent_tid, depth, spawn_kind)
        with cxr_praxis_dispatch(message, model=model,
                                 override_effort=reasoning_effort,
                                 session_id=cxr_session_id(),
                                 extras=extras) as ctx:
            response = real_model_call(message, effort=ctx.effort)
            ctx.record_outcome(response)
        return response

The context manager is the whole public surface. It handles:

  - pre-dispatch: score + allocate + emit signed ``alloc`` receipt.
  - effort translation: Praxis's ``effort`` → whatever the underlying
    provider wants (CXR mostly speaks OpenAI-style ``reasoning_effort``).
  - post-dispatch: emit signed ``outcome`` receipt with usage.
  - override path: if the caller supplied ``override_effort``, honour it
    and record it as ``decision="caller_override"``.

The implementation is dependency-free — no CXR import. CXR calls this
module, not the other way round, so there's nothing to mock in tests.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional

from ..allocation import Allocation, allocate_for_model
from ..allocator import BUDGET_TIERS, EFFORT_TIERS, TIER_FOR_SCORE, build_thinking_config, classify_model_family
from ..receipt import emit_record, next_turn_id, resolve_session_id
from ._outcome import emit_outcome, extract_usage


__all__ = [
    "CxrDispatchContext",
    "cxr_praxis_dispatch",
    "make_spawn_extras",
    "praxis_to_cxr_effort",
]


# ── Effort translation ─────────────────────────────────────────────────────

# CXR runs mostly GPT-5-class models whose ``reasoning_effort`` enum is
# ``low | medium | high``. Praxis's xhigh/max collapse to high, matching
# the LangChain adapter's rule. A caller who wants the extra tokens on
# a provider that supports it should pass ``override_effort`` explicitly.
_CXR_EFFORT_MAP = {
    None:     None,
    "low":    "low",
    "medium": "medium",
    "high":   "high",
    "xhigh":  "high",
    "max":    "high",
}


def praxis_to_cxr_effort(effort: Optional[str]) -> Optional[str]:
    """Down-cast Praxis's five-level effort enum to CXR's three-level one."""
    return _CXR_EFFORT_MAP.get(effort)


# ── Recursion-tree metadata ────────────────────────────────────────────────


def make_spawn_extras(
    parent_tid: Optional[int],
    depth: int,
    spawn_kind: str = "spawn_agent",
) -> Dict[str, Any]:
    """
    Build the ``extras`` payload for a CXR alloc receipt.

    ``spawn_kind`` is one of ``spawn_agent | rlm_query | rlm_map |
    rlm_propose | main``. ``depth`` is 0 for the root turn, 1 for its
    direct children, etc. ``parent_tid`` is the turn id of the spawner;
    ``None`` on the root turn.

    The schema is additive — existing ledgers keep verifying. Reports
    that know about these fields get a recursion-tree view; reports
    that don't ignore them.
    """
    return {
        "source": "cxr",
        "spawn_kind": spawn_kind,
        "depth": int(depth),
        "parent_tid": int(parent_tid) if parent_tid is not None else None,
    }


# ── Dispatch context ───────────────────────────────────────────────────────


@dataclass
class CxrDispatchContext:
    """
    What :func:`cxr_praxis_dispatch` yields to the user's ``with`` block.

    The caller uses ``ctx.effort`` / ``ctx.thinking_config`` /
    ``ctx.alloc`` to shape the outgoing request, then calls
    ``ctx.record_outcome(response)`` to emit the paired outcome receipt.
    """

    alloc: Allocation
    effort: Optional[str]
    thinking_config: Dict[str, Any]
    cxr_effort: Optional[str]

    def record_outcome(
        self,
        response: Any,
        *,
        stop_reason: Optional[str] = None,
        tool_calls: Optional[int] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        """Write the signed ``outcome`` receipt paired with this alloc."""
        emit_outcome(
            self.alloc.session_id,
            self.alloc.turn_id,
            usage_source=response,
            stop_reason=stop_reason or _peek_stop_reason(response),
            tool_calls=tool_calls,
            duration_ms=duration_ms,
        )


def _peek_stop_reason(response: Any) -> Optional[str]:
    """Best-effort stop_reason pulled from the response object."""
    for attr in ("stop_reason", "finish_reason"):
        v = getattr(response, attr, None)
        if isinstance(v, str):
            return v
    if isinstance(response, dict):
        return response.get("stop_reason") or response.get("finish_reason")
    meta = getattr(response, "response_metadata", None)
    if isinstance(meta, dict):
        return meta.get("stop_reason") or meta.get("finish_reason")
    return None


# ── The integration entry point ────────────────────────────────────────────


@contextmanager
def cxr_praxis_dispatch(
    message: str,
    *,
    model: str,
    session_id: Optional[str] = None,
    parent_tid: Optional[int] = None,
    depth: int = 0,
    spawn_kind: str = "spawn_agent",
    override_effort: Optional[str] = None,
    emit: bool = True,
) -> Iterator[CxrDispatchContext]:
    """
    CXR-side wrapper. Use as a context manager around your real model call.

    Parameters mirror CXR's existing dispatch signature:

      * ``message`` — the prompt/payload the child agent receives.
      * ``model`` — the model name CXR is about to invoke.
      * ``session_id`` — stable conversation id (usually the CXR session).
      * ``parent_tid``, ``depth``, ``spawn_kind`` — recursion metadata.
      * ``override_effort`` — if the caller already picked an effort tier
        (via explicit kwarg or thinking keyword), Praxis records that as
        the decision rather than re-scoring.

    Yields a :class:`CxrDispatchContext` with:
      * ``effort`` — Praxis's decided effort (``low/medium/high/xhigh/max``)
      * ``cxr_effort`` — down-cast to CXR's ``low/medium/high`` enum
      * ``thinking_config`` — the Anthropic-shape dict for Claude-family models
      * ``alloc`` — the full Allocation if you need ``(sid, tid)`` directly

    Does not hide exceptions — if the user's model call raises, the
    outcome receipt is not emitted (which is correct; there's no outcome
    to pair against). The alloc receipt is already on disk at that point,
    so the ledger stays honest: "we allocated, we never got an answer".
    """
    extras = make_spawn_extras(parent_tid, depth, spawn_kind)

    if override_effort is not None:
        alloc = _forced_allocation(
            prompt=message,
            model=model,
            effort=override_effort,
            session_id=session_id,
            extras=extras,
            emit=emit,
        )
    else:
        alloc = allocate_for_model(
            message,
            model,
            session={"session_id": session_id} if session_id else {},
            extras=extras,
            emit=emit,
        )

    ctx = CxrDispatchContext(
        alloc=alloc,
        effort=alloc.effort,
        thinking_config=alloc.thinking_config,
        cxr_effort=praxis_to_cxr_effort(alloc.effort),
    )
    yield ctx


# ── Caller-override path ───────────────────────────────────────────────────

_EFFORT_TO_SCORE = {
    None:     1,
    "low":    3,
    "medium": 5,
    "high":   7,
    "xhigh":  9,
    "max":    10,
}


def _forced_allocation(
    *,
    prompt: str,
    model: str,
    effort: str,
    session_id: Optional[str],
    extras: Dict[str, Any],
    emit: bool,
) -> Allocation:
    """
    Build an Allocation pinned to a caller-supplied effort level.

    This is the CXR equivalent of the hook's ``keyword_override`` path:
    when the user already knows what effort they want (via explicit
    kwarg, ``ultrathink`` in the prompt, etc.), Praxis respects the
    decision and just handles the bookkeeping.
    """
    score = _EFFORT_TO_SCORE.get(effort, 5)
    family = classify_model_family(model)
    sid = resolve_session_id({"session_id": session_id} if session_id else {})
    tid = next_turn_id(sid) if emit else 0

    alloc = Allocation(
        prompt_preview=prompt[:80],
        prompt_len=len(prompt),
        complexity=score,
        tier=TIER_FOR_SCORE[score],
        effort=EFFORT_TIERS[score],
        tokens=BUDGET_TIERS[score],
        model=model,
        model_family=family,
        thinking_config=build_thinking_config(score, family),
        session_id=sid,
        turn_id=tid,
        decision="caller_override",
        extras=extras,
    )

    if emit:
        emit_record(
            ledger_name="allocation-log.jsonl",
            record_type="alloc",
            session_id=sid,
            turn_id=tid,
            payload=alloc.as_payload(),
        )
    return alloc
