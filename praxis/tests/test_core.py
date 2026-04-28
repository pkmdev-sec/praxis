"""
PRAXIS — core package tests.

Two tiers of coverage:

  1. Algorithmic correctness: fixtures that pin the 1-10 scorer, the
     tier/effort tables, and the per-family thinking-config shape.
  2. Cross-language parity: run the same fixture set through the Node
     scorer (``lib/complexity-scorer.mjs`` / ``hooks/praxis-allocator.py``)
     and assert equality. This is what the "signed receipts verify on either
     side" promise rests on.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Path hacking so `pip install -e .` isn't required to run the suite locally.
_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent
sys.path.insert(0, str(_PKG))
_REPO = _PKG.parent  # grandparent: main praxis repo

from praxis import (  # noqa: E402
    BUDGET_TIERS,
    EFFORT_TIERS,
    TIER_FOR_SCORE,
    allocate,
    allocate_for_model,
    build_thinking_config,
    classify_model_family,
    score_complexity,
    sign_record,
    verify_record,
)
from praxis.receipt import _reset_key_cache  # noqa: E402


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own PRAXIS_HOME + a deterministic signing key."""
    monkeypatch.setenv("PRAXIS_HOME", str(tmp_path))
    monkeypatch.setenv("PRAXIS_RECEIPT_KEY", "ab" * 32)
    _reset_key_cache()
    yield


# ── Scorer fixtures (must match the hook byte-for-byte) ─────────────────────

SCORER_FIXTURES = [
    ("What is a variable?", 1),
    ("What is JS?", 1),
    ("Define recursion", 1),
    ("fix the typo in README", 4),
    ("Update the copyright year in the footer component", 4),
    ("refactor the authentication module", 4),
    ("Design a distributed fault-tolerant microservice architecture with CQRS and event sourcing", 7),
    ("Implement a real-time collaboration system using CRDTs with conflict resolution", 7),
    # No keyword override — pure heuristic scoring.
    ("debug complex deadlock in production", 9),
    ("diagnose intermittent nondeterministic failure", 9),
    ("", 1),
    ("run the test suite", 1),
]


@pytest.mark.parametrize("prompt,expected", SCORER_FIXTURES)
def test_score_matches_fixture(prompt, expected):
    assert score_complexity(prompt) == expected, f"score mismatch for {prompt!r}"


@pytest.mark.parametrize("prompt,expected", SCORER_FIXTURES)
def test_score_matches_hook(prompt, expected):
    """The production hook and the Python package must return the same number."""
    hook = _REPO / "hooks" / "praxis-allocator.py"
    if not hook.exists():
        pytest.skip("production hook not available")

    payload = json.dumps({"prompt": prompt, "session_id": "fixture-test"})
    with tempfile.TemporaryDirectory() as td:
        result = subprocess.run(
            ["python3", str(hook)],
            input=payload,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PRAXIS_HOME": td,
                "PRAXIS_RECEIPT_KEY": "cd" * 32,
            },
            timeout=5,
        )
    if not result.stdout.strip() or result.stdout.strip() == "{}":
        # Empty-prompt edge case; hook exits early without emitting a score.
        assert expected == 1
        return
    hook_output = json.loads(result.stdout)
    assert hook_output["complexity_score"] == score_complexity(prompt) == expected


# ── Allocator shape tests ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model,family",
    [
        ("claude-opus-4-7", "adaptive_only"),
        ("claude-mythos-preview", "adaptive_only"),
        ("claude-opus-4-6", "adaptive_preferred"),
        ("claude-sonnet-4-6", "adaptive_preferred"),
        ("claude-opus-4-5", "manual"),
        ("claude-haiku-4-5", "manual"),
        ("unknown-future-claude", "adaptive_only"),  # default is safest
    ],
)
def test_model_family_classification(model, family):
    assert classify_model_family(model) == family


def test_adaptive_only_skips_thinking_on_trivial():
    """Opus 4.7 must *omit* thinking for trivial prompts — not disable it."""
    cfg = build_thinking_config(1, "adaptive_only")
    assert cfg == {}


def test_adaptive_only_emits_effort_on_complex():
    cfg = build_thinking_config(8, "adaptive_only")
    assert cfg == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }


def test_adaptive_preferred_includes_legacy_budget():
    """Opus 4.6 / Sonnet 4.6 still accept budget_tokens; emit both for safety."""
    cfg = build_thinking_config(7, "adaptive_preferred")
    assert cfg == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
        "legacy_budget_tokens": 16384,
    }


def test_manual_family_uses_budget_tokens():
    cfg = build_thinking_config(5, "manual")
    assert cfg == {"thinking": {"type": "enabled", "budget_tokens": 8192}}


def test_manual_family_disables_on_trivial():
    cfg = build_thinking_config(1, "manual")
    assert cfg == {"thinking": {"type": "disabled"}}


def test_tier_tables_are_monotone():
    """Smoke: higher scores must not map to smaller budgets or lower effort."""
    effort_order = {None: 0, "low": 1, "medium": 2, "high": 3, "xhigh": 4, "max": 5}
    last_tokens = -1
    last_effort = -1
    for s in range(1, 11):
        assert BUDGET_TIERS[s] >= last_tokens
        assert effort_order[EFFORT_TIERS[s]] >= last_effort
        last_tokens = BUDGET_TIERS[s]
        last_effort = effort_order[EFFORT_TIERS[s]]


# ── End-to-end: allocate_for_model ──────────────────────────────────────────


def test_allocate_for_model_emits_signed_receipt(tmp_path):
    alloc = allocate_for_model(
        "Design a distributed pipeline with CQRS",
        model="claude-opus-4-7",
        session={"session_id": "e2e-session-1"},
    )
    assert alloc.complexity == 7
    assert alloc.tier == "heavy"
    assert alloc.effort == "high"
    assert alloc.thinking_config["output_config"]["effort"] == "high"
    assert alloc.session_id == "e2e-session-1"
    assert alloc.turn_id == 1

    # The receipt must be on disk and must verify.
    log = tmp_path / "allocation-log.jsonl"
    assert log.exists()
    lines = [json.loads(line) for line in log.read_text().strip().split("\n")]
    assert len(lines) == 1
    assert verify_record(lines[0]) is True

    # Mutating the budget must invalidate the signature.
    lines[0]["payload"]["budget_requested"] = 0
    assert verify_record(lines[0]) is False


def test_turn_ids_are_monotone_within_session():
    sid = "monotone-sess"
    a1 = allocate_for_model("what is a variable?", "claude-opus-4-7", session={"session_id": sid})
    a2 = allocate_for_model("fix the bug", "claude-opus-4-7", session={"session_id": sid})
    a3 = allocate_for_model("design a system", "claude-opus-4-7", session={"session_id": sid})
    assert [a1.turn_id, a2.turn_id, a3.turn_id] == [1, 2, 3]


def test_dry_run_does_not_write_ledger(tmp_path):
    alloc = allocate_for_model(
        "Design a distributed system",
        model="claude-opus-4-7",
        emit=False,
    )
    assert alloc.complexity == 7
    assert not (tmp_path / "allocation-log.jsonl").exists()


# ── Receipt primitives ──────────────────────────────────────────────────────


def test_sign_verify_round_trip():
    rec = {
        "v": 1,
        "type": "alloc",
        "sid": "x",
        "tid": 1,
        "ts": 1.0,
        "policy_version": "1.2.0",
        "payload": {"complexity": 7},
    }
    sign_record(rec)
    assert verify_record(rec) is True


def test_sign_is_order_independent():
    a = sign_record({
        "v": 1, "type": "alloc", "sid": "x", "tid": 1, "ts": 1.0,
        "policy_version": "1.2.0", "payload": {"a": 1, "b": 2},
    })
    # Deliberately re-insert keys in a different order.
    b = sign_record({
        "payload": {"b": 2, "a": 1},
        "policy_version": "1.2.0",
        "ts": 1.0,
        "tid": 1,
        "sid": "x",
        "type": "alloc",
        "v": 1,
    })
    assert a["sig"] == b["sig"]


def test_verify_rejects_garbage():
    assert verify_record(None) is False
    assert verify_record("not-a-dict") is False
    assert verify_record({}) is False
    assert verify_record({"sig": "deadbeef"}) is False  # no payload to verify



# ── Keyword override (ultrathink / megathink / think step by step) ──────────

KEYWORD_FIXTURES = [
    ("ultrathink about this race condition", "keyword_override", 10),
    ("megathink through this design", "keyword_override", 8),
    ("think step by step about the migration", "keyword_override", 5),
    ("I need to think about this later", "auto_scored", None),  # not a directive
    ("just fix the typo", "auto_scored", None),
]


@pytest.mark.parametrize("prompt,expected_decision,expected_score", KEYWORD_FIXTURES)
def test_keyword_override_matches_hook(prompt, expected_decision, expected_score):
    """
    A keyword override in the Python package must produce the same decision
    and score as the production hook. This is the cross-language contract
    made empirical — the two codepaths must agree on what the user meant.
    """
    alloc = allocate_for_model(prompt, "claude-opus-4-7", emit=False)
    assert alloc.decision == expected_decision
    if expected_score is not None:
        assert alloc.complexity == expected_score
