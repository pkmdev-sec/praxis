"""
PRAXIS — Anthropic adapter tests.

The real Anthropic SDK isn't importable in CI (and we don't want to burn
test-budget on real API calls anyway). We stub the ``anthropic`` module
with a tiny fake and assert:

  - ``thinking`` / ``output_config`` are spliced into ``messages.create``.
  - Usage fields land in the canonical bench-response dict.
  - API errors are caught and surfaced as a failure record, not a crash.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent.parent
sys.path.insert(0, str(_PKG))


# ── Stub the anthropic SDK ──────────────────────────────────────────────────


class _Usage:
    def __init__(self, input_tokens=100, output_tokens=500, **extras):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.output_tokens_details = extras.get("output_tokens_details")
        if "reasoning_tokens" in extras:
            self.reasoning_tokens = extras["reasoning_tokens"]


class _TextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _ThinkingBlock:
    def __init__(self, text):
        self.type = "thinking"
        self.thinking = text


class _FakeResponse:
    def __init__(self, text, *, usage=None, stop_reason="end_turn", include_thinking=False):
        blocks = [_TextBlock(text)]
        if include_thinking:
            blocks.insert(0, _ThinkingBlock("inner monologue"))
        self.content = blocks
        self.usage = usage or _Usage()
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self):
        self.last_kwargs = None
        self.fake_response = _FakeResponse(
            "reply text",
            usage=_Usage(reasoning_tokens=7200),
            stop_reason="end_turn",
        )
        self.raise_next = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if self.raise_next is not None:
            err = self.raise_next
            self.raise_next = None
            raise err
        return self.fake_response


class _APIStatusError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


class _FakeAnthropicClient:
    def __init__(self, *args, **kwargs):
        self.messages = _FakeMessages()


def _install_stub():
    mod = types.ModuleType("anthropic")
    mod.Anthropic = _FakeAnthropicClient
    mod.APIStatusError = _APIStatusError
    sys.modules["anthropic"] = mod
    return mod


@pytest.fixture(autouse=True)
def stub_anthropic():
    _install_stub()
    yield


# ── Tests ───────────────────────────────────────────────────────────────────


def test_adapter_splices_thinking_and_output_config():
    from praxis.bench.anthropic_adapter import anthropic_llm
    llm = anthropic_llm(model="claude-opus-4-7", max_tokens=4096)
    resp = llm("Design a thing", {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    })

    # The wrapper must have called messages.create with the Praxis fields set.
    last = llm._client.messages.last_kwargs
    assert last["model"] == "claude-opus-4-7"
    assert last["max_tokens"] == 4096
    assert last["thinking"] == {"type": "adaptive"}
    assert last["output_config"] == {"effort": "high"}
    assert last["messages"] == [{"role": "user", "content": "Design a thing"}]

    # Response canonical shape.
    assert resp["answer"] == "reply text"
    assert resp["thinking_used"] == 7200
    assert resp["input_tokens"] == 100
    assert resp["output_tokens"] == 500
    assert resp["stop_reason"] == "end_turn"
    assert isinstance(resp["duration_ms"], int)


def test_adapter_skips_thinking_blocks_from_answer():
    """Only text blocks become the answer. Thinking blocks are the SDK's
    internal reasoning trace — they must not reach the scorer."""
    from praxis.bench.anthropic_adapter import anthropic_llm
    llm = anthropic_llm(model="claude-opus-4-7", max_tokens=4096)
    llm._client.messages.fake_response = _FakeResponse(
        "the final answer",
        include_thinking=True,
        usage=_Usage(reasoning_tokens=2000),
    )
    resp = llm("prompt", {})
    assert resp["answer"] == "the final answer"
    assert "inner monologue" not in resp["answer"]


def test_adapter_extracts_reasoning_from_output_tokens_details():
    """Newer SDK shape: reasoning_tokens nested under output_tokens_details."""
    from praxis.bench.anthropic_adapter import anthropic_llm
    llm = anthropic_llm(model="claude-opus-4-7", max_tokens=4096)
    llm._client.messages.fake_response = _FakeResponse(
        "x",
        usage=_Usage(output_tokens_details={"reasoning_tokens": 3300}),
    )
    resp = llm("prompt", {})
    assert resp["thinking_used"] == 3300


def test_adapter_falls_back_to_output_tokens_when_no_reasoning_field():
    """Opus 4.7 rolls thinking into output_tokens."""
    from praxis.bench.anthropic_adapter import anthropic_llm
    llm = anthropic_llm(model="claude-opus-4-7", max_tokens=4096)
    llm._client.messages.fake_response = _FakeResponse(
        "x",
        usage=_Usage(input_tokens=50, output_tokens=1400),
    )
    resp = llm("prompt", {})
    # No reasoning_tokens attribute; fall back to output_tokens.
    assert resp["thinking_used"] == 1400


def test_adapter_surfaces_api_errors_as_failure_record():
    """A 429 must land in the ledger as a ``stop_reason=error:429`` row, not crash."""
    from praxis.bench.anthropic_adapter import anthropic_llm
    llm = anthropic_llm(model="claude-opus-4-7", max_tokens=4096)
    llm._client.messages.raise_next = _APIStatusError("rate limited", 429)

    resp = llm("prompt", {})
    assert resp["answer"] == ""
    assert resp["thinking_used"] == 0
    assert resp["stop_reason"] == "error:429"
    assert "rate limited" in resp["error"]


def test_adapter_omits_thinking_config_when_empty():
    """Bare arms send an empty config — the wrapper must NOT set thinking=... then."""
    from praxis.bench.anthropic_adapter import anthropic_llm
    llm = anthropic_llm(model="claude-opus-4-7", max_tokens=4096)
    llm("prompt", {})
    last = llm._client.messages.last_kwargs
    assert "thinking" not in last
    assert "output_config" not in last
