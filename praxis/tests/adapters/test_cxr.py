"""
PRAXIS — CXR adapter tests.

Verifies the three properties CXR integration has to satisfy:

  1. A recursion tree rooted at a parent turn produces correctly-linked
     alloc receipts, with ``parent_tid`` / ``depth`` / ``spawn_kind``
     preserved across nested spawns.
  2. Caller-supplied ``override_effort`` bypasses the scorer and records
     the decision as ``caller_override``.
  3. The ``record_outcome`` helper emits a paired outcome receipt that
     joins with the alloc on ``(sid, tid)``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent.parent
sys.path.insert(0, str(_PKG))

from praxis.adapters.cxr import (
    CxrDispatchContext,
    cxr_praxis_dispatch,
    make_spawn_extras,
    praxis_to_cxr_effort,
)
from praxis.receipt import _reset_key_cache


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PRAXIS_HOME", str(tmp_path))
    monkeypatch.setenv("PRAXIS_RECEIPT_KEY", "ab" * 32)
    _reset_key_cache()
    yield


# ── Effort translation ─────────────────────────────────────────────────────


def test_effort_translation_downcasts_for_openai():
    """xhigh/max must collapse to high — OpenAI's API has no finer grain."""
    assert praxis_to_cxr_effort("xhigh") == "high"
    assert praxis_to_cxr_effort("max") == "high"
    assert praxis_to_cxr_effort("medium") == "medium"
    assert praxis_to_cxr_effort(None) is None


def test_make_spawn_extras_tags_source_as_cxr():
    extras = make_spawn_extras(parent_tid=42, depth=2, spawn_kind="rlm_map")
    assert extras["source"] == "cxr"
    assert extras["spawn_kind"] == "rlm_map"
    assert extras["depth"] == 2
    assert extras["parent_tid"] == 42


def test_make_spawn_extras_allows_root_turn():
    """Root turn has no parent; parent_tid must be allowed as None."""
    extras = make_spawn_extras(parent_tid=None, depth=0, spawn_kind="main")
    assert extras["parent_tid"] is None
    assert extras["depth"] == 0


# ── Context-manager behaviour ──────────────────────────────────────────────


class _FakeResp:
    def __init__(self, text: str, reasoning_tokens: int = 0, stop_reason="end_turn"):
        self.content = text
        self.usage = {
            "input_tokens": 100,
            "output_tokens": 300,
            "output_tokens_details": {"reasoning_tokens": reasoning_tokens},
        }
        self.stop_reason = stop_reason


def test_dispatch_context_yields_effort_and_thinking_config(tmp_path):
    """A heavy-tier prompt must produce both effort + thinking_config."""
    with cxr_praxis_dispatch(
        "Design a distributed system with CQRS",
        model="claude-opus-4-7",
        session_id="cxr-test-1",
        depth=0,
        spawn_kind="main",
    ) as ctx:
        assert ctx.effort == "high"
        assert ctx.cxr_effort == "high"   # no downcast needed at high
        assert ctx.thinking_config["output_config"]["effort"] == "high"
        assert ctx.alloc.tier == "heavy"
        ctx.record_outcome(_FakeResp("ok", reasoning_tokens=12000))

    # Ledger must have both alloc + outcome, linked by (sid, tid).
    alloc_log = tmp_path / "allocation-log.jsonl"
    outcome_log = tmp_path / "outcome-log.jsonl"
    alloc = json.loads(alloc_log.read_text().strip().split("\n")[-1])
    outcome = json.loads(outcome_log.read_text().strip().split("\n")[-1])

    assert alloc["sid"] == outcome["sid"] == "cxr-test-1"
    assert alloc["tid"] == outcome["tid"]
    assert alloc["payload"]["source"] == "cxr"
    assert alloc["payload"]["spawn_kind"] == "main"
    assert alloc["payload"]["depth"] == 0
    assert alloc["payload"]["parent_tid"] is None
    assert outcome["payload"]["thinking_used"] == 12000


def test_recursion_tree_preserves_parent_tid(tmp_path):
    """A root turn spawning two children must leave three linked alloc rows."""
    sid = "cxr-tree-1"
    # Root turn — depth=0.
    with cxr_praxis_dispatch(
        "Design the whole system and then implement subsystems",
        model="claude-opus-4-7",
        session_id=sid,
        depth=0,
        spawn_kind="main",
    ) as root:
        root_tid = root.alloc.turn_id
        root.record_outcome(_FakeResp("root ok", reasoning_tokens=8000))

    # Two children at depth=1, each pointing back to root_tid.
    for child_prompt in ["refactor the auth module", "write the retry decorator"]:
        with cxr_praxis_dispatch(
            child_prompt,
            model="claude-opus-4-7",
            session_id=sid,
            parent_tid=root_tid,
            depth=1,
            spawn_kind="rlm_map",
        ) as child:
            child.record_outcome(_FakeResp("child ok", reasoning_tokens=1500))

    allocs = [json.loads(l) for l in (tmp_path / "allocation-log.jsonl").read_text().strip().split("\n")]
    # Three alloc rows for this session.
    ours = [a for a in allocs if a["sid"] == sid]
    assert len(ours) == 3

    by_tid = {a["tid"]: a["payload"] for a in ours}
    assert by_tid[root_tid]["depth"] == 0
    assert by_tid[root_tid]["parent_tid"] is None
    # Both children must point at the root's tid.
    children = [p for tid, p in by_tid.items() if tid != root_tid]
    assert len(children) == 2
    for c in children:
        assert c["parent_tid"] == root_tid
        assert c["depth"] == 1
        assert c["spawn_kind"] == "rlm_map"


def test_override_effort_records_caller_override(tmp_path):
    """When CXR hands us an explicit effort, the decision must reflect that."""
    sid = "cxr-override-1"
    with cxr_praxis_dispatch(
        "What is git?",                # trivial prompt; scorer would say 'none'
        model="claude-opus-4-7",
        session_id=sid,
        override_effort="high",        # but caller knows better
    ) as ctx:
        assert ctx.alloc.decision == "caller_override"
        assert ctx.effort == "high"
        assert ctx.alloc.tier == "heavy"
        ctx.record_outcome(_FakeResp("ok", reasoning_tokens=5000))

    allocs = [json.loads(l) for l in (tmp_path / "allocation-log.jsonl").read_text().strip().split("\n")]
    last = allocs[-1]
    assert last["payload"]["decision"] == "caller_override"
    assert last["payload"]["effort"] == "high"


def test_exception_in_user_block_does_not_emit_outcome(tmp_path):
    """
    If the user's model call raises, the outcome receipt is NOT emitted.
    Ledger must still show the alloc (we allocated; there's just no outcome
    yet) — that's the honest story, not a silently-dropped row.
    """
    sid = "cxr-except-1"
    with pytest.raises(RuntimeError):
        with cxr_praxis_dispatch(
            "Design a distributed system",
            model="claude-opus-4-7",
            session_id=sid,
        ):
            raise RuntimeError("model call exploded")

    allocs = [json.loads(l) for l in (tmp_path / "allocation-log.jsonl").read_text().strip().split("\n")]
    outcome_file = tmp_path / "outcome-log.jsonl"

    assert any(a["sid"] == sid for a in allocs), "alloc for this session must exist"
    # Outcome file may or may not exist; either way, no outcome for this sid.
    if outcome_file.exists():
        outcomes = [json.loads(l) for l in outcome_file.read_text().strip().split("\n") if l.strip()]
        assert not any(o["sid"] == sid for o in outcomes)
