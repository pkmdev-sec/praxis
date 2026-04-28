#!/usr/bin/env python3
"""
PRAXIS — Outcome Hook (closes the loop).

Attach to Claude Code's ``Stop`` hook (fires after the assistant finishes a
turn) to write an ``outcome`` record that matches the ``alloc`` record emitted
by ``praxis-allocator.py``. Together they form the Verification Layer: every
allocation decision can be audited against what actually happened.

Install (``~/.claude/settings.json``)::

    {
      "hooks": {
        "UserPromptSubmit": [{"command": "python3 ~/praxis/hooks/praxis-allocator.py"}],
        "Stop":             [{"command": "python3 ~/praxis/hooks/praxis-outcome.py"}]
      }
    }

The ``Stop`` payload Claude Code sends us is not fully documented, so the hook
treats every field defensively: anything missing is recorded as null rather
than crashing. What we care about most is the *reasoning token count actually
consumed* — that's the signal that converts Praxis from an open-loop estimator
into a self-calibrating allocator.

Fields extracted (best-effort; any may be null):

  thinking_used   int   actual reasoning tokens spent (Anthropic: usage.reasoning_tokens)
  input_tokens    int   usage.input_tokens
  output_tokens   int   usage.output_tokens
  tool_calls      int   number of tool_use blocks in this turn
  duration_ms     int   wall-clock time for the turn
  stop_reason     str   "end_turn" | "max_tokens" | "stop_sequence" | "tool_use" | ...
  retry_flag      bool  set by allocator on next turn if prompt looks like a retry

Reading these lets the ledger compute:

  utilization    = thinking_used / budget_requested   (over-allocation signal)
  regret_score   = under-allocation (retry) + over-allocation (unused budget)
  per-tier stats  that the calibration tool in ``bin/praxis`` consumes
"""

from __future__ import annotations

import json
import sys

from _praxis_lib import (
    emit_record,
    resolve_session_id,
    peek_turn_id,
)


def _deep_get(obj, *path):
    """Walk nested dict/list path, returning None on any miss."""
    cur = obj
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and isinstance(key, int) and 0 <= key < len(cur):
            cur = cur[key]
        else:
            return None
    return cur


def _extract_usage(data: dict) -> dict:
    """
    Extract token counts from whatever shape Claude Code hands us.

    The payload varies by Claude Code version; we try the known shapes in
    order of likelihood and return whatever we find. Missing fields are
    emitted as None so downstream tooling can distinguish "not measured"
    from "zero".
    """
    candidates = [
        data.get("usage"),
        _deep_get(data, "response", "usage"),
        _deep_get(data, "message", "usage"),
        _deep_get(data, "turn", "usage"),
        _deep_get(data, "last_message", "usage"),
    ]
    usage = next((c for c in candidates if isinstance(c, dict)), {})

    return {
        "thinking_used": usage.get("reasoning_tokens")
                         or usage.get("thinking_tokens")
                         or _deep_get(usage, "output_tokens_details", "reasoning_tokens"),
        "input_tokens":  usage.get("input_tokens")
                         or usage.get("prompt_tokens"),
        "output_tokens": usage.get("output_tokens")
                         or usage.get("completion_tokens"),
        "cache_read":    usage.get("cache_read_input_tokens")
                         or usage.get("cache_creation_input_tokens"),
    }


def _count_tool_calls(data: dict) -> int | None:
    """Count tool_use blocks in the assistant's final message, if visible."""
    blocks = (
        _deep_get(data, "message", "content")
        or _deep_get(data, "response", "content")
        or _deep_get(data, "last_message", "content")
    )
    if not isinstance(blocks, list):
        return None
    return sum(1 for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use")


def _duration_ms(data: dict) -> int | None:
    for key in ("duration_ms", "latency_ms", "elapsed_ms"):
        v = data.get(key)
        if isinstance(v, (int, float)):
            return int(v)
    return None


def _stop_reason(data: dict) -> str | None:
    for path in (("stop_reason",), ("message", "stop_reason"), ("response", "stop_reason")):
        v = _deep_get(data, *path)
        if isinstance(v, str):
            return v
    return None


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print(json.dumps({}))
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}

        session_id = resolve_session_id(data)
        # The outcome pairs with the most recently issued turn id — allocator
        # bumps the counter on UserPromptSubmit, so ``peek`` gives the turn we
        # want to close.
        turn_id = peek_turn_id(session_id)

        usage = _extract_usage(data)
        payload = {
            **usage,
            "tool_calls":    _count_tool_calls(data),
            "duration_ms":   _duration_ms(data),
            "stop_reason":   _stop_reason(data),
        }

        emit_record(
            ledger_name="outcome-log.jsonl",
            record_type="outcome",
            session_id=session_id,
            turn_id=turn_id,
            payload=payload,
        )

        used = payload.get("thinking_used")
        print(
            f"[PRAXIS] outcome sid={session_id[:8]} tid={turn_id} "
            f"thinking_used={used} tool_calls={payload.get('tool_calls')} "
            f"stop={payload.get('stop_reason')}",
            file=sys.stderr,
        )

        # Stop hooks aren't acted on by Claude Code; emit empty JSON so the
        # hook pipeline stays clean.
        print(json.dumps({}))

    except Exception as e:  # pragma: no cover - defensive
        print(json.dumps({"error": f"praxis-outcome: {e}"}), file=sys.stderr)
        print(json.dumps({}))


if __name__ == "__main__":
    main()
