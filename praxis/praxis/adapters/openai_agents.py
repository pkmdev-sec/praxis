"""
PRAXIS — OpenAI Agents SDK adapter.

Drives ``ModelSettings.resolve()`` per turn so the reasoning effort is
chosen by Praxis instead of hard-coded at ``Agent(...)`` construction.

Install::

    pip install praxis[openai-agents]

Use::

    from agents import Agent, Runner
    from praxis.adapters.openai_agents import PraxisRunHooks

    agent = Agent(name="Coder", model="gpt-5.3-codex")
    hooks = PraxisRunHooks(session_id="my-session")

    result = Runner.run_sync(agent, "Design a distributed pipeline", hooks=hooks)
    # hooks internally adjusted model_settings.reasoning.effort per turn
    # and emitted alloc/outcome receipts.

The adapter uses the public ``RunHooks`` / ``on_turn_start`` interface
(openai/openai-agents-python #2911). If your installed version is older
than ``v0.14`` you'll need to upgrade — earlier versions don't expose the
per-turn hook point we need.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Optional

try:
    from agents import ModelSettings, RunHooks  # type: ignore
    try:
        from agents.model_settings import Reasoning  # type: ignore
    except ImportError:  # pragma: no cover - older layouts
        from agents.models.reasoning import Reasoning  # type: ignore
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "praxis.adapters.openai_agents requires openai-agents>=0.14. "
        "Install with: pip install 'praxis[openai-agents]'"
    ) from e

from ..allocation import allocate_for_model
from ._outcome import emit_outcome


# OpenAI accepts only low/medium/high on ``reasoning.effort`` as of v0.14.
# Praxis's xhigh/max collapse to high; minimal is our "no effort wanted".
_EFFORT_OPENAI = {
    None:     None,
    "low":    "low",
    "medium": "medium",
    "high":   "high",
    "xhigh":  "high",
    "max":    "high",
}


class PraxisRunHooks(RunHooks):
    """
    ``RunHooks`` implementation that picks reasoning effort per turn.

    Call flow per turn (from the Agents SDK):

      1. SDK invokes :meth:`on_turn_start` with the agent + current input.
      2. We score the input, decide the effort level, and patch
         ``run_context.model_settings`` in place via ``resolve()``.
      3. SDK sends the request.
      4. SDK invokes :meth:`on_turn_end` with the turn's output.
      5. We emit the paired ``outcome`` receipt.

    The last human message in the input is what we score. If the input is
    a single string (``Runner.run_sync(agent, "…")``), we use it directly.
    """

    def __init__(self, session_id: Optional[str] = None):
        super().__init__()
        self._session_id = session_id
        # (session_id, turn_id) of the active turn so on_turn_end can pair.
        self._inflight: dict = {}

    # ── Hook entry points ──────────────────────────────────────────────────

    async def on_turn_start(self, context, agent, input_items) -> None:  # type: ignore[override]
        prompt = _last_user_message(input_items)
        model = _resolve_agent_model(agent)

        session = {"session_id": self._session_id} if self._session_id else {}
        alloc = allocate_for_model(prompt, model, session=session)

        # Patch the agent's model_settings for *this turn only*. ModelSettings
        # is a frozen dataclass in v0.14+, so we build a fresh object and
        # swap it onto the run context.
        effort = _EFFORT_OPENAI.get(alloc.effort)
        override = ModelSettings(
            reasoning=Reasoning(effort=effort) if effort else None,
        )
        base = getattr(context, "model_settings", None) or ModelSettings()
        if hasattr(base, "resolve"):
            context.model_settings = base.resolve(override)
        else:  # pragma: no cover - shim for older/custom ModelSettings
            context.model_settings = replace(base, reasoning=override.reasoning)

        # Stash for the matching on_turn_end.
        self._inflight[id(context)] = (alloc.session_id, alloc.turn_id)

    async def on_turn_end(self, context, agent, output) -> None:  # type: ignore[override]
        ids = self._inflight.pop(id(context), None)
        if not ids:
            return
        sid, tid = ids
        emit_outcome(
            sid,
            tid,
            usage_source=output,
            stop_reason=_extract_stop_reason(output),
            tool_calls=_count_tool_calls(output),
        )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _last_user_message(input_items: Any) -> str:
    """Extract the most recent user message from whatever the SDK gave us."""
    if isinstance(input_items, str):
        return input_items
    if isinstance(input_items, list):
        for item in reversed(input_items):
            if isinstance(item, dict):
                if item.get("role") == "user":
                    content = item.get("content")
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        return "\n".join(
                            p.get("text", "") if isinstance(p, dict) else str(p)
                            for p in content
                        )
            elif getattr(item, "role", None) == "user":
                return str(getattr(item, "content", "") or "")
    return ""


def _resolve_agent_model(agent: Any) -> str:
    """Extract the model string from the Agent, matching Praxis defaults on miss."""
    model = getattr(agent, "model", None)
    if isinstance(model, str) and model.strip():
        return model.strip()
    # Newer SDK wraps model in a dataclass/string-union.
    name = getattr(model, "model", None) or getattr(model, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return "gpt-5.3"


def _extract_stop_reason(output: Any) -> Optional[str]:
    for path in (
        ("final_output",),
        ("message", "stop_reason"),
        ("response", "finish_reason"),
        ("stop_reason",),
        ("finish_reason",),
    ):
        cur = output
        for key in path:
            cur = getattr(cur, key, None) if not isinstance(cur, dict) else cur.get(key)
            if cur is None:
                break
        if isinstance(cur, str):
            return cur
    return None


def _count_tool_calls(output: Any) -> Optional[int]:
    items = getattr(output, "tool_calls", None) or getattr(output, "new_items", None)
    if isinstance(items, list):
        return sum(
            1 for i in items
            if getattr(i, "type", None) == "tool_call"
            or (isinstance(i, dict) and i.get("type") == "tool_call")
        )
    return None


__all__ = ["PraxisRunHooks"]
