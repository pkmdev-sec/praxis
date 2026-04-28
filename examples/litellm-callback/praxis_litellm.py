"""
PRAXIS × LiteLLM integration
============================

A LiteLLM ``CustomLogger`` that runs the Praxis complexity scorer on each
inbound request and injects the right reasoning-budget field for the target
model, then emits OpenInference-compatible telemetry on response so Langfuse,
Phoenix, Helicone, and any OTel collector can plot "budget chosen vs
reasoning tokens used vs judged quality" without further wiring.

Supports two provider families out of the box:

- **Anthropic Claude** — routes through ``effort`` on Opus 4.7 / Mythos /
  adaptive-preferred Opus 4.6 / Sonnet 4.6, and falls back to
  ``thinking.budget_tokens`` on Opus 4.5 and earlier.
- **OpenAI o-series** — sets ``reasoning_effort={"low","medium","high"}``.

The "policy" (complexity → tier → effort) is the same one the Praxis
UserPromptSubmit hook uses; this file just adapts the output to LiteLLM's
``pre_api_call`` hook shape.

Installation (minimal)
----------------------

    pip install litellm
    # copy this file somewhere on your PYTHONPATH, then:

    import litellm
    from praxis_litellm import PraxisCallback
    litellm.callbacks = [PraxisCallback()]

    # Now every completion() call is auto-budgeted:
    litellm.completion(
        model="claude-opus-4-7",
        messages=[{"role": "user", "content": "Design a distributed cache"}],
    )

With an OTel SDK installed (``pip install opentelemetry-sdk``) the callback
also emits ``praxis.*`` span attributes; without it, telemetry is silently
skipped so the callback stays dependency-light for non-OTel users.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

try:
    from litellm.integrations.custom_logger import CustomLogger  # type: ignore
except ImportError:  # pragma: no cover - exercised only on environments w/o litellm
    class CustomLogger:  # type: ignore
        """Fallback base class used only when litellm is not importable."""

        def log_pre_api_call(self, model, messages, kwargs):  # noqa: D401
            raise NotImplementedError

        async def async_log_pre_api_call(self, model, messages, kwargs):
            raise NotImplementedError

        def log_success_event(self, kwargs, response_obj, start_time, end_time):
            raise NotImplementedError

        async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
            raise NotImplementedError


log = logging.getLogger("praxis.litellm")


# ── Complexity scorer (ported from hooks/praxis-allocator.py) ─────────────

_KEYWORD_TIERS = {
    "simple":   (1, [r"\bwhat is\b", r"\bdefine\b", r"\bexplain\b", r"\bhow to\b",
                     r"\blist\b", r"\bshow me\b", r"\btell me\b", r"\bwhat does\b"]),
    "moderate": (4, [r"\bfix\b", r"\bmodify\b", r"\bchange\b", r"\bupdate\b",
                     r"\badd\b", r"\bremove\b", r"\brefactor\b", r"\bimplement\b",
                     r"\bcreate\b", r"\bwrite\b", r"\bbug\b", r"\berror\b"]),
    "complex":  (7, [r"\bdesign\b", r"\barchitect\b", r"\bsystem\b", r"\bscalable\b",
                     r"\bmigrat", r"\boptimiz", r"\bperformance\b", r"\bsecurity\b",
                     r"\bdistributed\b", r"\bmicroservic", r"\bpipeline\b"]),
    "advanced": (9, [r"\bdebug\s+complex", r"\brace\s+condition", r"\bmemory\s+leak",
                     r"\bconcurrency", r"\bdeadlock", r"\bmulti.?step",
                     r"\broot\s+cause", r"\bintermittent", r"\bnondeterministic",
                     r"\bcomplex\s+issue", r"\bfull\s+stack"]),
}
_BUDGET_TIERS = {1: 0, 2: 0, 3: 2048, 4: 2048, 5: 8192, 6: 8192,
                 7: 16384, 8: 16384, 9: 32768, 10: 32768}
_EFFORT_TIERS = {1: None, 2: None, 3: "low", 4: "low", 5: "medium", 6: "medium",
                 7: "high", 8: "high", 9: "xhigh", 10: "max"}
_TIER_NAMES = {0: "none", 2048: "light", 8192: "medium", 16384: "heavy", 32768: "max"}

_MODEL_FAMILIES = [
    (re.compile(r"^claude-mythos",     re.I), "adaptive_only"),
    (re.compile(r"^claude-opus-4-7",   re.I), "adaptive_only"),
    (re.compile(r"^claude-opus-4-6",   re.I), "adaptive_preferred"),
    (re.compile(r"^claude-sonnet-4-6", re.I), "adaptive_preferred"),
    (re.compile(r"^claude-haiku-4-5",  re.I), "manual"),
    (re.compile(r"^claude-(opus-4-5|opus-4-1|opus-4\b|sonnet-4-5|sonnet-4\b|haiku-4|sonnet-3-7)", re.I), "manual"),
    (re.compile(r"^(o1|o3|o4|gpt-5.*reason)", re.I), "openai_reasoning"),
]


def _score_complexity(text: str) -> int:
    if not text or not isinstance(text, str):
        return 1
    score = 1
    for name, (tier_score, patterns) in _KEYWORD_TIERS.items():
        for pat in patterns:
            if re.search(pat, text, re.I):
                score = max(score, tier_score)
    wc = len(text.split())
    if   wc > 150: score = max(score, 7)
    elif wc > 80:  score = max(score, 5)
    elif wc > 30:  score = max(score, 3)
    if text.count("```") // 2 > 1 or text.count("?") > 2:
        score = min(10, score + 1)
    return min(10, max(1, score))


def _classify(model: str) -> str:
    for pat, fam in _MODEL_FAMILIES:
        if pat.search(model or ""):
            return fam
    return "adaptive_only"


@dataclass
class PraxisDecision:
    complexity: int
    tier: str
    tokens: int
    effort: str | None
    model: str
    model_family: str

    def as_otel_attrs(self, decision_mode: str = "auto_scored") -> dict[str, Any]:
        return {
            "praxis.complexity_score": self.complexity,
            "praxis.tier_chosen": self.tier,
            "praxis.budget_requested": self.tokens,
            "praxis.model": self.model,
            "praxis.model_family": self.model_family,
            "praxis.effort_chosen": self.effort or "",
            "praxis.decision_mode": decision_mode,
        }


def decide(prompt: str, model: str) -> PraxisDecision:
    """Pure function; does no IO. Exposed for unit tests."""
    complexity = _score_complexity(prompt)
    tokens = _BUDGET_TIERS[complexity]
    return PraxisDecision(
        complexity=complexity,
        tier=_TIER_NAMES[tokens],
        tokens=tokens,
        effort=_EFFORT_TIERS[complexity],
        model=model,
        model_family=_classify(model),
    )


# ── LiteLLM CustomLogger ──────────────────────────────────────────────────

class PraxisCallback(CustomLogger):
    """
    LiteLLM callback that sets the reasoning budget per prompt and records
    telemetry on completion.
    """

    def __init__(self, tracer=None, logger: logging.Logger | None = None):
        self.tracer = tracer  # optional OpenTelemetry tracer
        self.log = logger or log

    # ---- pre-call: inject thinking config ----

    def log_pre_api_call(self, model, messages, kwargs):  # sync path
        self._inject(model, messages, kwargs)

    async def async_log_pre_api_call(self, model, messages, kwargs):
        self._inject(model, messages, kwargs)

    def _inject(self, model, messages, kwargs):
        # LiteLLM calls log_pre_api_call even for trivial cases; guard against
        # recursion by stamping a sentinel on kwargs.
        if kwargs.get("_praxis_applied"):
            return
        prompt = self._last_user_message(messages)
        if not prompt:
            return
        decision = decide(prompt, model)
        self._apply(decision, kwargs)
        kwargs["_praxis_applied"] = True
        # Also stash the decision so the post-call hook can correlate.
        kwargs["_praxis_decision"] = decision
        self.log.info(
            "[PRAXIS] model=%s family=%s score=%s tier=%s effort=%s tokens=%s",
            model, decision.model_family, decision.complexity,
            decision.tier, decision.effort, decision.tokens,
        )

    @staticmethod
    def _last_user_message(messages) -> str:
        if not messages:
            return ""
        for m in reversed(messages):
            if m.get("role") == "user":
                c = m.get("content", "")
                return c if isinstance(c, str) else json.dumps(c)
        return ""

    @staticmethod
    def _apply(d: PraxisDecision, kwargs: dict) -> None:
        # Don't overwrite an explicit user setting — honour hand-crafted calls.
        if d.model_family == "adaptive_only":
            if d.effort is None:
                kwargs.pop("thinking", None)
                return
            kwargs.setdefault("thinking", {"type": "adaptive"})
            kwargs.setdefault("output_config", {}).setdefault("effort", d.effort)
        elif d.model_family == "adaptive_preferred":
            if d.effort is None:
                kwargs.setdefault("thinking", {"type": "disabled"})
                return
            kwargs.setdefault("thinking", {"type": "adaptive"})
            kwargs.setdefault("output_config", {}).setdefault("effort", d.effort)
        elif d.model_family == "manual":
            if d.tokens == 0:
                kwargs.setdefault("thinking", {"type": "disabled"})
            else:
                kwargs.setdefault("thinking", {"type": "enabled", "budget_tokens": d.tokens})
        elif d.model_family == "openai_reasoning":
            # OpenAI o-series uses reasoning_effort enum (low/medium/high).
            effort = d.effort
            if effort in ("xhigh", "max"):
                effort = "high"
            if effort is None:
                kwargs.pop("reasoning_effort", None)
            else:
                kwargs.setdefault("reasoning_effort", effort)

    # ---- post-call: emit OTel span attrs + log utilization ----

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._record(kwargs, response_obj)

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._record(kwargs, response_obj)

    def _record(self, kwargs, response):
        decision: PraxisDecision | None = kwargs.get("_praxis_decision")
        if decision is None:
            return
        used = self._extract_reasoning_tokens(response)
        utilization = (used / decision.tokens) if decision.tokens > 0 else 0.0
        attrs = {
            **decision.as_otel_attrs(),
            "praxis.reasoning_tokens_used": used,
            "praxis.budget_utilization": round(utilization, 3),
            "praxis.over_allocated": int(decision.tokens >= 8192 and utilization < 0.25),
        }
        self._emit(attrs)
        self.log.info(
            "[PRAXIS] used=%d / %d (%.1f%%) %s",
            used, decision.tokens, utilization * 100,
            "over_allocated" if attrs["praxis.over_allocated"] else "ok",
        )

    @staticmethod
    def _extract_reasoning_tokens(response) -> int:
        # LiteLLM normalises usage into `response.usage`; the reasoning token
        # field is vendor-specific, so we probe all known spellings.
        try:
            u = getattr(response, "usage", None) or (
                response.get("usage", {}) if isinstance(response, dict) else {}
            )
            if not u:
                return 0
            as_dict = u if isinstance(u, dict) else getattr(u, "model_dump", lambda: u.__dict__)()
            # Anthropic Claude 4:
            ct_details = as_dict.get("completion_tokens_details") or {}
            if "reasoning_tokens" in ct_details:
                return int(ct_details["reasoning_tokens"])
            # Anthropic raw field:
            if "thinking_tokens" in as_dict:
                return int(as_dict["thinking_tokens"])
            # OpenAI o-series:
            otd = as_dict.get("completion_tokens_details") or {}
            if "reasoning_tokens" in otd:
                return int(otd["reasoning_tokens"])
            return 0
        except Exception:
            return 0

    def _emit(self, attrs: dict) -> None:
        if self.tracer is None:
            return
        try:
            span = self.tracer.get_current_span() if hasattr(self.tracer, "get_current_span") else None
            if span is None:
                return
            for k, v in attrs.items():
                span.set_attribute(k, v)
        except Exception:
            # Telemetry must never break the request path.
            pass


__all__ = ["PraxisCallback", "PraxisDecision", "decide"]
