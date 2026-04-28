"""
PRAXIS — Anthropic SDK adapter for the benchmark harness.

Wraps the official ``anthropic`` Python SDK so the caller can write:

    from praxis.bench.anthropic_adapter import anthropic_llm
    llm = anthropic_llm(model="claude-opus-4-7", max_tokens=8192)

and hand ``llm`` to a :class:`praxis.bench.PolicyArm`. That's the entire
difference between "toy benchmark" and "real SWE-bench run".

Three contracts worth calling out:

  1. **`thinking_config` is applied verbatim.** The Praxis policy layer
     already produced the right Anthropic request shape — we don't re-
     interpret it here, we just spread it into ``messages.create``. This
     keeps the adapter ~30 lines and the round-trip auditable.
  2. **Usage extraction matches `_outcome.py`.** The bench adapter returns
     the same ``{answer, thinking_used, input_tokens, output_tokens,
     stop_reason}`` shape the runner expects. Reasoning tokens come from
     ``usage.output_tokens`` for Opus 4.7 (thinking is rolled into output
     on adaptive-only models); we also probe newer fields when present.
  3. **No silent fallback if `anthropic` isn't installed.** The import is
     eager at adapter-construction time so the caller gets a clear error.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional


__all__ = ["anthropic_llm", "AnthropicBenchLLM"]


class AnthropicBenchLLM:
    """
    Bench-compatible LLM wrapper around ``anthropic.Anthropic``.

    Call surface: ``llm(prompt: str, thinking_config: dict) -> dict`` —
    the exact signature :class:`praxis.bench.PolicyArm` expects.

    ``system`` and ``max_tokens`` are fixed per wrapper instance. Per-call
    overrides (e.g. `thinking={...}`, `output_config={...}`) come in via
    the ``thinking_config`` argument — that's what Praxis sets per turn.
    """

    def __init__(
        self,
        *,
        model: str,
        max_tokens: int = 8192,
        system: Optional[str] = None,
        client: Optional[Any] = None,
        max_retries: int = 2,
    ):
        try:
            import anthropic  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "praxis.bench.anthropic_adapter requires the 'anthropic' package. "
                "Install with: pip install anthropic"
            ) from e

        self._anthropic = anthropic
        self._client = client or anthropic.Anthropic(max_retries=max_retries)
        self._model = model
        self._max_tokens = max_tokens
        self._system = system

    def __call__(self, prompt: str, thinking_config: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.monotonic()
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self._system:
            kwargs["system"] = self._system

        # Splice the Praxis-decided fields directly. ``thinking`` and
        # ``output_config`` are what the capability layer produces; if
        # the model family is ``manual`` Praxis sends ``{thinking: {type:
        # "enabled", budget_tokens: N}}`` which is also accepted.
        for key in ("thinking", "output_config"):
            if key in thinking_config:
                kwargs[key] = thinking_config[key]

        try:
            resp = self._client.messages.create(**kwargs)
        except self._anthropic.APIStatusError as e:
            # Surface a structured failure so the benchmark records it as a
            # failed task rather than crashing the whole sweep. The run can
            # resume from the ledger.
            return {
                "answer": "",
                "thinking_used": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "stop_reason": f"error:{e.status_code}",
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "error": str(e),
            }

        return {
            "answer": _concat_text(resp.content),
            "thinking_used": _extract_reasoning_tokens(resp),
            "input_tokens": getattr(resp.usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(resp.usage, "output_tokens", 0) or 0,
            "stop_reason": getattr(resp, "stop_reason", None),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }


def _concat_text(content) -> str:
    """Join the text blocks from a Messages API response."""
    if not content:
        return ""
    parts = []
    for block in content:
        btype = getattr(block, "type", None)
        if btype == "text":
            text = getattr(block, "text", "")
            if text:
                parts.append(text)
        # We deliberately skip ``thinking`` blocks — they're the internal
        # reasoning trace, not the answer the evaluator should score.
    return "\n".join(parts)


def _extract_reasoning_tokens(resp: Any) -> int:
    """
    Pull reasoning tokens out of a Messages API response.

    On Opus 4.7 (adaptive thinking) the thinking tokens are rolled into
    ``usage.output_tokens``; there's no separate counter on the base
    Messages API. Newer beta fields may surface ``reasoning_tokens``
    explicitly — we probe for them so the adapter doesn't go stale the
    day Anthropic ships the cleaner surface.
    """
    usage = getattr(resp, "usage", None)
    if usage is None:
        return 0
    # Direct attribute on the usage object, if it lands.
    for attr in ("reasoning_tokens", "thinking_tokens"):
        v = getattr(usage, attr, None)
        if isinstance(v, (int, float)):
            return int(v)
    # Nested details dict used on some SDK versions.
    details = getattr(usage, "output_tokens_details", None)
    if isinstance(details, dict):
        v = details.get("reasoning_tokens")
        if isinstance(v, (int, float)):
            return int(v)
    # Fallback: output_tokens includes thinking on adaptive-only models.
    return int(getattr(usage, "output_tokens", 0) or 0)


def anthropic_llm(
    *,
    model: str,
    max_tokens: int = 8192,
    system: Optional[str] = None,
    client: Optional[Any] = None,
    max_retries: int = 2,
) -> Callable[[str, Dict[str, Any]], Dict[str, Any]]:
    """
    Factory sugar — returns a ready-to-use ``(prompt, thinking_config) -> dict``
    callable around :class:`AnthropicBenchLLM`.

    The callable is stateless between calls (new ``messages.create`` each
    invocation); set ``client`` only if you need a shared rate-limit pool
    across multiple adapters.
    """
    return AnthropicBenchLLM(
        model=model,
        max_tokens=max_tokens,
        system=system,
        client=client,
        max_retries=max_retries,
    )
