"""
Shared outcome-receipt helper for framework adapters.

Every adapter has the same job after the model returns: read reasoning-token
usage from whatever shape the SDK produced, pair it with the most recent
``alloc`` receipt for the session, and emit an ``outcome`` record. This
module centralises that logic so the LangChain, OpenAI Agents, and future
adapters all write identical receipts.
"""

from __future__ import annotations

from typing import Any, Optional

from ..receipt import emit_record, peek_turn_id


def _deep_get(obj: Any, *path) -> Any:
    """Walk a nested dict/list path, returning None on any miss."""
    cur = obj
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and isinstance(key, int) and 0 <= key < len(cur):
            cur = cur[key]
        elif hasattr(cur, key):  # Pydantic / dataclass fallthrough
            cur = getattr(cur, key)
        else:
            return None
    return cur


def extract_usage(source: Any) -> dict:
    """
    Best-effort extraction of reasoning/input/output token counts from any
    of the shapes providers return today:

      - Anthropic Messages API: ``usage.output_tokens``,
        ``usage.cache_creation_input_tokens``; reasoning tokens are rolled
        into output. LangChain mirrors this as ``response.usage_metadata``.
      - OpenAI Responses API: ``usage.output_tokens_details.reasoning_tokens``.
      - LangChain AIMessage: ``response_metadata["usage"]`` or
        ``usage_metadata`` (the AIMessage attribute).
      - Agents SDK: ``RawResponsesStreamEvent`` payloads surface the same.

    Fields absent in the source come back as ``None``. That matters for the
    honest-regret report: "not measured" must be distinguishable from "zero".
    """
    candidates = [
        source if isinstance(source, dict) else None,
        _deep_get(source, "usage"),
        _deep_get(source, "usage_metadata"),
        _deep_get(source, "response_metadata", "usage"),
        _deep_get(source, "response", "usage"),
        _deep_get(source, "message", "usage"),
    ]
    usage = next((c for c in candidates if isinstance(c, dict)), {})

    # Reasoning tokens live in different places per provider.
    reasoning = (
        usage.get("reasoning_tokens")
        or usage.get("thinking_tokens")
        or _deep_get(usage, "output_tokens_details", "reasoning_tokens")
        # LangChain AIMessage output_token_details sometimes nests it here.
        or _deep_get(usage, "output_token_details", "reasoning")
    )

    return {
        "thinking_used": reasoning,
        "input_tokens":  usage.get("input_tokens") or usage.get("prompt_tokens"),
        "output_tokens": usage.get("output_tokens") or usage.get("completion_tokens"),
        "cache_read":    usage.get("cache_read_input_tokens")
                         or usage.get("cache_creation_input_tokens"),
    }


def emit_outcome(
    session_id: str,
    turn_id: Optional[int],
    *,
    usage_source: Any = None,
    tool_calls: Optional[int] = None,
    stop_reason: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> dict:
    """
    Append a signed ``outcome`` record to ``outcome-log.jsonl``.

    ``turn_id`` defaults to the most recent tid issued for the session,
    matching how the Claude Code ``Stop`` hook pairs outcomes against
    allocations.
    """
    tid = turn_id if turn_id is not None else peek_turn_id(session_id)
    payload = {
        **extract_usage(usage_source),
        "tool_calls":   tool_calls,
        "stop_reason":  stop_reason,
        "duration_ms":  duration_ms,
    }
    return emit_record(
        ledger_name="outcome-log.jsonl",
        record_type="outcome",
        session_id=session_id,
        turn_id=tid,
        payload=payload,
    )
