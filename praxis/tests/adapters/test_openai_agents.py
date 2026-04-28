"""
PRAXIS — OpenAI Agents SDK adapter tests.

Like the LangChain tests, we stub the Agents SDK surface rather than
requiring a real install. The contract we care about:

  - ``on_turn_start`` patches ``context.model_settings`` with the right
    ``reasoning.effort`` level for the scored complexity.
  - ``on_turn_end`` emits a paired outcome receipt with usage.
  - ``(sid, tid)`` pairs across the two hooks.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import types
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PKG_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_PKG_ROOT))


# ── Stub openai-agents SDK ──────────────────────────────────────────────────


def _install_stub_agents():
    """
    Build a minimal ``agents`` module that exposes ``ModelSettings``,
    ``Reasoning``, and ``RunHooks``. The stub mirrors the real v0.14 shape:
    ModelSettings is a frozen-ish dataclass with a ``resolve()`` method.
    """

    from dataclasses import dataclass, field, replace
    from typing import Any, Optional

    @dataclass
    class Reasoning:
        effort: Optional[str] = None

    @dataclass
    class ModelSettings:
        reasoning: Optional[Reasoning] = None
        max_tokens: Optional[int] = None
        extras: dict = field(default_factory=dict)

        def resolve(self, override: "ModelSettings") -> "ModelSettings":
            return replace(
                self,
                reasoning=override.reasoning if override.reasoning is not None else self.reasoning,
                max_tokens=override.max_tokens if override.max_tokens is not None else self.max_tokens,
            )

    class RunHooks:
        """Real SDK's RunHooks has async on_turn_start/on_turn_end methods."""
        async def on_turn_start(self, context, agent, input_items): pass
        async def on_turn_end(self, context, agent, output): pass

    agents_mod = types.ModuleType("agents")
    agents_mod.ModelSettings = ModelSettings
    agents_mod.Reasoning = Reasoning
    agents_mod.RunHooks = RunHooks

    model_settings_mod = types.ModuleType("agents.model_settings")
    model_settings_mod.ModelSettings = ModelSettings
    model_settings_mod.Reasoning = Reasoning

    sys.modules["agents"] = agents_mod
    sys.modules["agents.model_settings"] = model_settings_mod
    return ModelSettings, Reasoning


ModelSettings, Reasoning = _install_stub_agents()

from praxis.adapters.openai_agents import PraxisRunHooks  # noqa: E402
from praxis.receipt import _reset_key_cache  # noqa: E402


# ── Test infra ──────────────────────────────────────────────────────────────


class FakeAgent:
    def __init__(self, model: str):
        self.model = model


class FakeRunContext:
    """Minimal RunContext stub — only ``.model_settings`` is touched."""
    def __init__(self):
        self.model_settings = ModelSettings()


class FakeOutput:
    """Mimics what the Agents SDK hands to on_turn_end: usage + stop_reason."""
    def __init__(self, reasoning_tokens=None, input_tokens=None, output_tokens=None, stop_reason="end_turn"):
        self.usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "output_tokens_details": {"reasoning_tokens": reasoning_tokens},
        }
        self.stop_reason = stop_reason
        self.new_items = []


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PRAXIS_HOME", str(tmp_path))
    monkeypatch.setenv("PRAXIS_RECEIPT_KEY", "ab" * 32)
    _reset_key_cache()
    yield


# ── Tests ───────────────────────────────────────────────────────────────────


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if sys.version_info < (3, 10) \
        else asyncio.run(coro)


def test_on_turn_start_patches_effort_for_complex_prompt(tmp_path):
    hooks = PraxisRunHooks(session_id="agents-test-1")
    agent = FakeAgent("gpt-5.3-codex")
    context = FakeRunContext()

    _run(hooks.on_turn_start(context, agent, "Design a distributed fault-tolerant system"))

    assert context.model_settings.reasoning is not None
    assert context.model_settings.reasoning.effort == "high"
    assert id(context) in hooks._inflight

    alloc_file = tmp_path / "allocation-log.jsonl"
    alloc = json.loads(alloc_file.read_text().strip().split("\n")[-1])
    assert alloc["payload"]["model"] == "gpt-5.3-codex"
    assert alloc["payload"]["complexity"] == 7


def test_on_turn_start_skips_reasoning_for_trivial_prompt():
    hooks = PraxisRunHooks(session_id="agents-test-2")
    agent = FakeAgent("gpt-5.3")
    context = FakeRunContext()
    _run(hooks.on_turn_start(context, agent, "What is a variable?"))
    # Trivial → effort None → reasoning stays None on the settings.
    assert context.model_settings.reasoning is None


def test_xhigh_and_max_downcast_to_high_on_openai():
    """OpenAI's enum is low/medium/high only; xhigh/max must collapse."""
    hooks = PraxisRunHooks(session_id="agents-test-3")
    agent = FakeAgent("gpt-5.3-codex")
    context = FakeRunContext()

    _run(hooks.on_turn_start(context, agent, "ultrathink about this race condition"))
    assert context.model_settings.reasoning.effort == "high"


def test_on_turn_end_emits_paired_outcome(tmp_path):
    hooks = PraxisRunHooks(session_id="agents-test-4")
    agent = FakeAgent("gpt-5.3")
    context = FakeRunContext()

    _run(hooks.on_turn_start(context, agent, "Design a pipeline"))
    _run(hooks.on_turn_end(context, agent, FakeOutput(reasoning_tokens=7200, input_tokens=200, output_tokens=500)))

    alloc = json.loads((tmp_path / "allocation-log.jsonl").read_text().strip().split("\n")[-1])
    outcome = json.loads((tmp_path / "outcome-log.jsonl").read_text().strip().split("\n")[-1])

    assert outcome["sid"] == alloc["sid"]
    assert outcome["tid"] == alloc["tid"]
    assert outcome["payload"]["thinking_used"] == 7200
    assert outcome["payload"]["input_tokens"] == 200
    assert outcome["payload"]["output_tokens"] == 500
    assert outcome["payload"]["stop_reason"] == "end_turn"


def test_on_turn_end_without_start_is_silent(tmp_path):
    """If on_turn_end somehow fires without a matching start, no crash."""
    hooks = PraxisRunHooks(session_id="agents-test-5")
    agent = FakeAgent("gpt-5.3")
    context = FakeRunContext()
    _run(hooks.on_turn_end(context, agent, FakeOutput(reasoning_tokens=100)))
    # Nothing should have been written.
    assert not (tmp_path / "outcome-log.jsonl").exists()
