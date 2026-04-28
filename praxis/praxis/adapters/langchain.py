"""
PRAXIS — LangChain adapter.

Wraps any LangChain chat model (``ChatAnthropic``, ``ChatOpenAI``,
``ChatVertexAI``, …) in a :class:`PraxisBudget` Runnable that decides the
reasoning budget from the last human message and binds the right vendor
kwargs before dispatching.

Install::

    pip install praxis[langchain]

Use::

    from langchain_anthropic import ChatAnthropic
    from praxis.adapters.langchain import PraxisBudget

    llm = ChatAnthropic(model="claude-opus-4-7", max_tokens=4096)
    praxis_llm = PraxisBudget(llm, session_id="my-session")

    # Regular LangChain call — Praxis transparently scores, budgets, and
    # records an alloc+outcome receipt pair.
    reply = praxis_llm.invoke([HumanMessage("Design a distributed pipeline")])

The wrapper is a ``Runnable`` subclass so it composes with every LangChain
primitive: ``RunnableSequence``, ``with_fallbacks``, ``with_retry``, LCEL
pipes, the whole lot.
"""

from __future__ import annotations

from typing import Any, List, Optional

try:
    from langchain_core.runnables import Runnable, RunnableConfig
    from langchain_core.messages import BaseMessage, HumanMessage
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "praxis.adapters.langchain requires langchain-core. "
        "Install with: pip install 'praxis[langchain]'"
    ) from e

from ..allocation import allocate_for_model
from ..escalation import should_escalate, escalate
from ..policy import Policy, DEFAULT_POLICY
from ..reflection import ReflectionResult, reflect, self_reflect_prompt, SELF_STRATEGY
from ._outcome import emit_outcome


# ── Provider plumbing ───────────────────────────────────────────────────────


def _resolve_model_name(llm: Any) -> str:
    """
    Best-effort model-name extraction. LangChain chat models expose the name
    differently per provider; we check the common paths and fall back to
    ``claude-sonnet-4-6`` if none work (matches the Python package default).
    """
    for attr in ("model", "model_name", "model_id"):
        v = getattr(llm, attr, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # Some providers stash it on ``_default_params`` or similar.
    for attr in ("_llm_type",):
        v = getattr(llm, attr, None)
        if isinstance(v, str):
            return v
    return "claude-sonnet-4-6"


def _provider_kind(llm: Any) -> str:
    """Crude provider detection — enough to pick the right kwargs to bind."""
    cls = type(llm).__name__.lower()
    if "anthropic" in cls:
        return "anthropic"
    if "openai" in cls or "azureopenai" in cls:
        return "openai"
    if "vertex" in cls or "gemini" in cls or "google" in cls:
        return "google"
    return "unknown"


def _last_user_prompt(messages: Any) -> str:
    """Find the most recent HumanMessage, or treat a raw string as the prompt."""
    if isinstance(messages, str):
        return messages
    if isinstance(messages, BaseMessage):
        return str(messages.content) if messages.content else ""
    if isinstance(messages, list):
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage) or getattr(msg, "type", "") == "human":
                content = getattr(msg, "content", "")
                if isinstance(content, list):
                    # Multi-part content blocks — concatenate text parts.
                    parts = [
                        p.get("text", "") if isinstance(p, dict) else str(p)
                        for p in content
                    ]
                    return "\n".join(filter(None, parts))
                return str(content or "")
    return ""


def _to_bind_kwargs(provider: str, thinking_config: dict, effort: Optional[str]) -> dict:
    """
    Translate Praxis's canonical ``thinking_config`` dict into the kwargs a
    given provider's LangChain wrapper accepts.

    Anthropic path: LangChain's ``ChatAnthropic`` takes ``thinking`` verbatim,
    plus a newer ``output_config`` kwarg for Opus 4.6+.
    OpenAI path: ``reasoning_effort`` enum.
    Google path: ``thinking_budget`` integer (0 off, -1 dynamic).
    """
    # For Anthropic we key off thinking_config; for OpenAI we key off effort;
    # for Google we read the legacy budget. Don't short-circuit on empty
    # thinking_config — OpenAI never populates it.
    if provider == "anthropic":
        kwargs = {}
        if "thinking" in thinking_config:
            kwargs["thinking"] = thinking_config["thinking"]
        if "output_config" in thinking_config:
            kwargs["output_config"] = thinking_config["output_config"]
        return kwargs

    if provider == "openai":
        # OpenAI accepts low/medium/high. We down-cast xhigh/max → high.
        if effort is None:
            return {}
        level = effort
        if level in ("xhigh", "max"):
            level = "high"
        return {"reasoning_effort": level}

    if provider == "google":
        # Gemini: `thinking_budget` is an integer token count.
        tokens = thinking_config.get("legacy_budget_tokens") or 0
        if "thinking" in thinking_config and thinking_config["thinking"].get("type") == "enabled":
            tokens = thinking_config["thinking"].get("budget_tokens", tokens)
        return {"thinking_budget": tokens} if tokens else {}

    return {}


# ── The Runnable ────────────────────────────────────────────────────────────


class PraxisBudget(Runnable):
    """
    Wrap any LangChain chat model with Praxis's per-call reasoning-budget
    policy.

    Each ``invoke`` / ``ainvoke`` call:

      1. Extracts the last human message from the input.
      2. Calls :func:`praxis.allocate_for_model` (signed ``alloc`` receipt).
      3. Binds the resulting thinking/effort kwargs onto the underlying LLM.
      4. Dispatches to the LLM.
      5. Emits a signed ``outcome`` receipt with the response's usage data.

    The wrapped LLM is exposed as ``.llm`` in case callers need to set a
    base ``thinking`` config that Praxis's per-call override stacks on top of.
    """

    def __init__(
        self,
        llm: Any,
        *,
        session_id: Optional[str] = None,
        model: Optional[str] = None,
        emit_receipts: bool = True,
        policy: Policy = DEFAULT_POLICY,
        reflector: Optional[Any] = None,
    ):
        super().__init__()
        self.llm = llm
        self._session_id = session_id
        self._model = model or _resolve_model_name(llm)
        self._provider = _provider_kind(llm)
        self._emit = emit_receipts
        self._policy = policy
        # ``reflector`` is a callable (prompt, answer) -> ReflectionResult.
        # Defaults to a self-reflection pass on the wrapped llm.
        self._reflector = reflector

    @property
    def InputType(self):  # noqa: N802 (LangChain convention)
        return self.llm.InputType

    @property
    def OutputType(self):  # noqa: N802
        return self.llm.OutputType

    def _allocate(self, input: Any) -> tuple:
        """Score the prompt and return (allocation, bound_llm)."""
        prompt = _last_user_prompt(input)
        session = {"session_id": self._session_id} if self._session_id else {}
        alloc = allocate_for_model(
            prompt,
            self._model,
            session=session,
            emit=self._emit,
        )
        bind_kwargs = _to_bind_kwargs(self._provider, alloc.thinking_config, alloc.effort)
        bound = self.llm.bind(**bind_kwargs) if bind_kwargs else self.llm
        return alloc, bound

    def invoke(self, input: Any, config: Optional[RunnableConfig] = None, **kwargs) -> Any:
        prompt = _last_user_prompt(input)
        alloc, bound = self._allocate(input)

        # --- primary dispatch with escalation loop ---
        response = bound.invoke(input, config=config, **kwargs)
        if self._emit:
            emit_outcome(
                alloc.session_id,
                alloc.turn_id,
                usage_source=response,
                stop_reason=_extract_stop_reason(response),
                tool_calls=_count_tool_calls(response),
            )

        hop = 0
        while should_escalate(alloc, response, self._policy, current_hop=hop):
            hop += 1
            alloc = escalate(
                alloc, prompt, self._model,
                session={"session_id": self._session_id} if self._session_id else None,
                current_hop=hop - 1,
            )
            bind_kwargs = _to_bind_kwargs(self._provider, alloc.thinking_config, alloc.effort)
            bound = self.llm.bind(**bind_kwargs) if bind_kwargs else self.llm
            response = bound.invoke(input, config=config, **kwargs)
            if self._emit:
                emit_outcome(
                    alloc.session_id,
                    alloc.turn_id,
                    usage_source=response,
                    stop_reason=_extract_stop_reason(response),
                    tool_calls=_count_tool_calls(response),
                )

        # --- optional reflection pass ---
        if self._policy.for_tier(alloc.tier).reflect:
            reflector = self._reflector or self._default_self_reflector()
            answer_text = _response_text(response)
            result = reflect(alloc, prompt, answer_text, reflector)
            # Caller opts into "use the revision if one was produced"; we
            # don't overwrite the AIMessage automatically because the shape
            # differs per provider. Return the ReflectionResult on a known
            # attribute so downstream code can pick it up.
            try:
                setattr(response, "praxis_reflection", result)
            except AttributeError:
                pass
        return response

    async def ainvoke(self, input: Any, config: Optional[RunnableConfig] = None, **kwargs) -> Any:
        prompt = _last_user_prompt(input)
        alloc, bound = self._allocate(input)

        response = await bound.ainvoke(input, config=config, **kwargs)
        if self._emit:
            emit_outcome(
                alloc.session_id,
                alloc.turn_id,
                usage_source=response,
                stop_reason=_extract_stop_reason(response),
                tool_calls=_count_tool_calls(response),
            )

        hop = 0
        while should_escalate(alloc, response, self._policy, current_hop=hop):
            hop += 1
            alloc = escalate(
                alloc, prompt, self._model,
                session={"session_id": self._session_id} if self._session_id else None,
                current_hop=hop - 1,
            )
            bind_kwargs = _to_bind_kwargs(self._provider, alloc.thinking_config, alloc.effort)
            bound = self.llm.bind(**bind_kwargs) if bind_kwargs else self.llm
            response = await bound.ainvoke(input, config=config, **kwargs)
            if self._emit:
                emit_outcome(
                    alloc.session_id,
                    alloc.turn_id,
                    usage_source=response,
                    stop_reason=_extract_stop_reason(response),
                    tool_calls=_count_tool_calls(response),
                )

        if self._policy.for_tier(alloc.tier).reflect:
            reflector = self._reflector or self._default_self_reflector(async_mode=True)
            answer_text = _response_text(response)
            # Self-reflection in async still calls the user's Reflector
            # callable, which may itself be async — we accept both.
            import inspect
            raw = reflector(prompt, answer_text)
            if inspect.isawaitable(raw):
                result = await raw
            else:
                result = raw
            from ..reflection import reflect as _reflect_sync  # noqa: F401
            # Don't double-emit: ``reflect`` emits the receipt, so we call it
            # via its public shape with a pre-computed result by wrapping the
            # result in a pass-through reflector.
            reflect(alloc, prompt, answer_text, lambda _p, _a: result)
            try:
                setattr(response, "praxis_reflection", result)
            except AttributeError:
                pass
        return response

    # --- default self-reflector (used when caller doesn't supply one) -----

    def _default_self_reflector(self, async_mode: bool = False):
        """Re-prompt the wrapped llm with the self-reflection template."""
        llm = self.llm
        model_name = self._model

        def _sync(prompt: str, answer: str) -> ReflectionResult:
            template = self_reflect_prompt(prompt, answer)
            # Re-prompt with a fresh, budget-minimal call — reflection should
            # not itself burn max tokens.
            from langchain_core.messages import HumanMessage
            resp = llm.invoke([HumanMessage(template)])
            text = _response_text(resp)
            verdict = "ratify" if text.strip().startswith("RATIFY") else "revise"
            revision = None if verdict == "ratify" else text
            return ReflectionResult(
                verdict=verdict,
                revision=revision,
                findings=[],
                reflector_model=model_name,
                strategy=SELF_STRATEGY,
            )

        async def _async(prompt: str, answer: str) -> ReflectionResult:
            template = self_reflect_prompt(prompt, answer)
            from langchain_core.messages import HumanMessage
            resp = await llm.ainvoke([HumanMessage(template)])
            text = _response_text(resp)
            verdict = "ratify" if text.strip().startswith("RATIFY") else "revise"
            revision = None if verdict == "ratify" else text
            return ReflectionResult(
                verdict=verdict,
                revision=revision,
                findings=[],
                reflector_model=model_name,
                strategy=SELF_STRATEGY,
            )

        return _async if async_mode else _sync


# ── Response parsing helpers ────────────────────────────────────────────────


def _extract_stop_reason(response: Any) -> Optional[str]:
    """Pull ``stop_reason`` / ``finish_reason`` out of a LangChain AIMessage."""
    meta = getattr(response, "response_metadata", None) or {}
    for key in ("stop_reason", "finish_reason"):
        v = meta.get(key)
        if isinstance(v, str):
            return v
    return None


def _count_tool_calls(response: Any) -> Optional[int]:
    """Count tool_calls on a LangChain AIMessage (None if not a chat-model result)."""
    tool_calls = getattr(response, "tool_calls", None)
    if isinstance(tool_calls, list):
        return len(tool_calls)
    return None





def _response_text(response: Any) -> str:
    """Extract text from a LangChain AIMessage-ish object for reflection."""
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(part.get("text", ""))
            else:
                parts.append(str(part))
        return "\n".join(filter(None, parts))
    return str(content or "")


__all__ = ["PraxisBudget", "PraxisCapabilityLayer"]
PraxisCapabilityLayer = PraxisBudget
