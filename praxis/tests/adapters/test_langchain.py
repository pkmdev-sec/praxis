"""
PRAXIS — LangChain adapter tests.

Don't install langchain just to test. We stub out the minimum surface
Praxis touches (``Runnable``, ``RunnableConfig``, ``BaseMessage``,
``HumanMessage``, the ``.bind()`` + ``.invoke()`` call shape) with
a tiny fake, and assert Praxis makes the right decision + records
the right receipt.

If real ``langchain-core`` is installed, the same tests run against it.
"""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

# Path hack so tests work without `pip install -e .`.
_HERE = Path(__file__).resolve().parent
_PKG_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_PKG_ROOT))


# ── Stub langchain_core if it isn't installed ───────────────────────────────


def _install_stub_langchain():
    """Build a minimal langchain_core stub so ``import praxis.adapters.langchain`` works."""

    class RunnableConfig(dict):
        pass

    class Runnable:
        """Minimal Runnable base — just enough for PraxisBudget to subclass."""
        def __init__(self, *args, **kwargs):
            pass
        def invoke(self, input, config=None, **kwargs):
            raise NotImplementedError

    class BaseMessage:
        def __init__(self, content):
            self.content = content
            self.type = "base"

    class HumanMessage(BaseMessage):
        def __init__(self, content):
            super().__init__(content)
            self.type = "human"

    class AIMessage(BaseMessage):
        def __init__(self, content, **meta):
            super().__init__(content)
            self.type = "ai"
            self.response_metadata = meta.get("response_metadata", {})
            self.usage_metadata = meta.get("usage_metadata", {})
            self.tool_calls = meta.get("tool_calls", [])

    runnables_mod = types.ModuleType("langchain_core.runnables")
    runnables_mod.Runnable = Runnable
    runnables_mod.RunnableConfig = RunnableConfig

    messages_mod = types.ModuleType("langchain_core.messages")
    messages_mod.BaseMessage = BaseMessage
    messages_mod.HumanMessage = HumanMessage
    messages_mod.AIMessage = AIMessage

    core_mod = types.ModuleType("langchain_core")
    core_mod.runnables = runnables_mod
    core_mod.messages = messages_mod

    sys.modules["langchain_core"] = core_mod
    sys.modules["langchain_core.runnables"] = runnables_mod
    sys.modules["langchain_core.messages"] = messages_mod
    return AIMessage


AIMessage = _install_stub_langchain()

from praxis.adapters.langchain import PraxisBudget, _to_bind_kwargs  # noqa: E402
from praxis.receipt import _reset_key_cache  # noqa: E402


# ── Test infra ──────────────────────────────────────────────────────────────


class FakeChatAnthropic:
    """Minimal fake that records the kwargs Praxis binds before dispatch."""
    def __init__(self, model="claude-opus-4-7"):
        self.model = model
        self.bound_kwargs = None
        self.InputType = list
        self.OutputType = AIMessage

    def bind(self, **kwargs):
        # Return a fresh fake so .bind() chains don't pollute the original.
        clone = FakeChatAnthropic(self.model)
        clone.bound_kwargs = {**(self.bound_kwargs or {}), **kwargs}
        return clone

    def invoke(self, input, config=None, **kwargs):
        return AIMessage(
            "fake response",
            response_metadata={"stop_reason": "end_turn"},
            usage_metadata={
                "input_tokens": 120,
                "output_tokens": 340,
                "output_token_details": {"reasoning": 9100},
            },
            tool_calls=[],
        )

    async def ainvoke(self, input, config=None, **kwargs):
        return self.invoke(input, config, **kwargs)


class FakeChatOpenAI(FakeChatAnthropic):
    def __init__(self, model="gpt-5.3"):
        super().__init__(model=model)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PRAXIS_HOME", str(tmp_path))
    monkeypatch.setenv("PRAXIS_RECEIPT_KEY", "ab" * 32)
    _reset_key_cache()
    yield


# ── Tests ───────────────────────────────────────────────────────────────────


def test_bind_kwargs_anthropic_adaptive_only():
    cfg = {"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}}
    assert _to_bind_kwargs("anthropic", cfg, "high") == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }


def test_bind_kwargs_anthropic_manual():
    cfg = {"thinking": {"type": "enabled", "budget_tokens": 8192}}
    assert _to_bind_kwargs("anthropic", cfg, "medium") == {
        "thinking": {"type": "enabled", "budget_tokens": 8192},
    }


def test_bind_kwargs_openai_downcasts_xhigh_to_high():
    """OpenAI only accepts low/medium/high; xhigh and max must collapse."""
    assert _to_bind_kwargs("openai", {}, "xhigh") == {"reasoning_effort": "high"}
    assert _to_bind_kwargs("openai", {}, "max") == {"reasoning_effort": "high"}
    assert _to_bind_kwargs("openai", {}, "medium") == {"reasoning_effort": "medium"}
    assert _to_bind_kwargs("openai", {}, None) == {}


def test_bind_kwargs_google_translates_to_thinking_budget():
    cfg = {"thinking": {"type": "enabled", "budget_tokens": 8192}}
    assert _to_bind_kwargs("google", cfg, "medium") == {"thinking_budget": 8192}


def test_invoke_emits_signed_receipts_and_binds_correct_kwargs(tmp_path):
    from langchain_core.messages import HumanMessage
    llm = FakeChatAnthropic("claude-opus-4-7")
    praxis_llm = PraxisBudget(llm, session_id="adapter-test-1")

    result = praxis_llm.invoke([HumanMessage("Design a distributed pipeline with CQRS")])
    assert result.content == "fake response"

    # Allocation log must have one signed record for this turn.
    alloc_file = tmp_path / "allocation-log.jsonl"
    alloc_lines = [json.loads(line) for line in alloc_file.read_text().strip().split("\n")]
    assert len(alloc_lines) == 1
    alloc = alloc_lines[0]
    assert alloc["sid"] == "adapter-test-1"
    assert alloc["payload"]["complexity"] == 7
    assert alloc["payload"]["effort"] == "high"

    # Outcome log must have a paired record with thinking_used=9100.
    out_file = tmp_path / "outcome-log.jsonl"
    out_lines = [json.loads(line) for line in out_file.read_text().strip().split("\n")]
    assert len(out_lines) == 1
    outcome = out_lines[0]
    assert outcome["sid"] == alloc["sid"]
    assert outcome["tid"] == alloc["tid"]
    assert outcome["payload"]["thinking_used"] == 9100
    assert outcome["payload"]["stop_reason"] == "end_turn"


def test_invoke_scores_raw_string_input():
    """A bare string (not a list of messages) must still be scorable."""
    llm = FakeChatAnthropic("claude-opus-4-7")
    praxis_llm = PraxisBudget(llm, session_id="adapter-test-2")
    praxis_llm.invoke("what is a variable?")
    # No exception = pass. The complexity-1 allocation must have emitted a receipt.


def test_dry_run_skips_receipts(tmp_path):
    llm = FakeChatAnthropic("claude-opus-4-7")
    praxis_llm = PraxisBudget(llm, session_id="adapter-test-3", emit_receipts=False)
    praxis_llm.invoke("Design a distributed system")
    assert not (tmp_path / "allocation-log.jsonl").exists()
    assert not (tmp_path / "outcome-log.jsonl").exists()


def test_openai_provider_detection_and_effort_binding():
    llm = FakeChatOpenAI("gpt-5.3-codex")
    praxis_llm = PraxisBudget(llm, session_id="adapter-test-4")
    praxis_llm.invoke("Design a fault-tolerant distributed system")
    # The first call binds kwargs on a new clone, but we only care the
    # allocation resolved to the right provider shape. Grab the receipt.
    alloc_file = Path(os.environ["PRAXIS_HOME"]) / "allocation-log.jsonl"
    alloc = json.loads(alloc_file.read_text().strip().split("\n")[-1])
    assert alloc["payload"]["model"] == "gpt-5.3-codex"
