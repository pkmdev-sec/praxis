"""
PRAXIS — Capability primitives tests.

Cover the three new modules:

  - praxis.policy       — tier → TierPolicy lookup, overrides, config-dict load.
  - praxis.escalation   — should_escalate gating + escalate() bookkeeping.
  - praxis.reflection   — reflector callable contract + receipt emission.

These tests assert on the *ledger*, because receipts are the user-facing
artefact. If escalate() doesn't produce a signed escalation record that
bin/praxis verify accepts, the feature is broken regardless of what the
Python API returns.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent
sys.path.insert(0, str(_PKG))

from praxis import (  # noqa: E402
    DEFAULT_POLICY,
    Policy,
    TIER_LADDER,
    TierPolicy,
    Allocation,
    allocate_for_model,
    escalate,
    should_escalate,
    reflect,
    ReflectionResult,
    SELF_STRATEGY,
    DROIDX_STRATEGY,
    verify_record,
)
from praxis.receipt import _reset_key_cache  # noqa: E402


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PRAXIS_HOME", str(tmp_path))
    monkeypatch.setenv("PRAXIS_RECEIPT_KEY", "ab" * 32)
    _reset_key_cache()
    yield


# ── Policy ──────────────────────────────────────────────────────────────────


def test_default_policy_amplifiers_fire_at_heavy():
    heavy = DEFAULT_POLICY.for_tier("heavy")
    assert heavy.escalate is True
    assert heavy.reflect is True
    assert heavy.max_escalation_hops >= 1


def test_default_policy_no_amplifiers_at_light():
    """Cheap path stays cheap — essential so capability-first doesn't mean 'always burn tokens'."""
    assert DEFAULT_POLICY.for_tier("light").escalate is False
    assert DEFAULT_POLICY.for_tier("light").reflect is False


def test_default_policy_no_escalate_at_max():
    """max has no successor to escalate into."""
    m = DEFAULT_POLICY.for_tier("max")
    assert m.escalate is False
    assert m.reflect is True  # but reflection still pays back


def test_policy_override_merges_without_losing_defaults():
    """Overriding heavy shouldn't wipe the default for max."""
    custom = Policy().override(
        heavy=TierPolicy(escalate=True, reflect=False),
    )
    # heavy is overridden
    assert custom.for_tier("heavy").reflect is False
    # max keeps the default
    assert custom.for_tier("max").reflect is True


def test_policy_from_dict_yaml_friendly():
    p = Policy.from_dict({
        "heavy": {"escalate": True, "reflect": True, "max_escalation_hops": 2},
    })
    h = p.for_tier("heavy")
    assert h.max_escalation_hops == 2
    assert h.escalate and h.reflect


# ── Escalation ──────────────────────────────────────────────────────────────


class _FakeResp:
    """Minimal stand-in for an LLM response with a stop_reason."""
    def __init__(self, stop_reason):
        self.stop_reason = stop_reason


def test_should_escalate_true_on_max_tokens_heavy_tier():
    alloc = allocate_for_model(
        "Design a distributed pipeline with CQRS",
        "claude-opus-4-7",
        emit=False,
    )
    assert alloc.tier == "heavy"
    resp = _FakeResp("max_tokens")
    assert should_escalate(alloc, resp, DEFAULT_POLICY) is True


def test_should_escalate_false_on_end_turn():
    alloc = allocate_for_model(
        "Design a distributed pipeline with CQRS",
        "claude-opus-4-7",
        emit=False,
    )
    resp = _FakeResp("end_turn")
    assert should_escalate(alloc, resp, DEFAULT_POLICY) is False


def test_should_escalate_respects_hop_ceiling():
    alloc = allocate_for_model(
        "Design a distributed pipeline with CQRS",
        "claude-opus-4-7",
        emit=False,
    )
    resp = _FakeResp("max_tokens")
    # First hop ok (current=0, max=1); second not (current=1, max=1).
    assert should_escalate(alloc, resp, DEFAULT_POLICY, current_hop=0) is True
    assert should_escalate(alloc, resp, DEFAULT_POLICY, current_hop=1) is False


def test_should_escalate_false_at_max_tier():
    """max is the ceiling — no successor, no escalation."""
    alloc = allocate_for_model(
        "ultrathink about this race condition",
        "claude-opus-4-7",
        emit=False,
    )
    assert alloc.tier == "max"
    resp = _FakeResp("max_tokens")
    assert should_escalate(alloc, resp, DEFAULT_POLICY) is False


def test_escalate_emits_signed_record_and_bumps_tier(tmp_path):
    original = allocate_for_model(
        "Design a distributed pipeline",
        "claude-opus-4-7",
        session={"session_id": "esc-1"},
    )
    assert original.tier == "heavy"

    escalated = escalate(
        original,
        "Design a distributed pipeline",
        "claude-opus-4-7",
        session={"session_id": "esc-1"},
        current_hop=0,
    )

    # The escalated allocation must be one tier higher.
    assert TIER_LADDER.index(escalated.tier) == TIER_LADDER.index(original.tier) + 1
    assert escalated.tier == "max"
    assert escalated.effort == "max"
    assert escalated.decision == "escalated"
    # It reuses the same session, but its turn id advances.
    assert escalated.session_id == original.session_id
    assert escalated.turn_id == original.turn_id + 1

    # The escalation-log must have a signed record linking back.
    log = tmp_path / "escalation-log.jsonl"
    assert log.exists()
    lines = [json.loads(l) for l in log.read_text().strip().split("\n")]
    assert len(lines) == 1
    rec = lines[0]
    assert verify_record(rec) is True
    assert rec["payload"]["escalated_from"] == original.turn_id
    assert rec["payload"]["from_tier"] == "heavy"
    assert rec["payload"]["to_tier"] == "max"
    assert rec["payload"]["hop"] == 1


def test_escalate_at_ceiling_is_noop():
    """Attempting to escalate max returns the same allocation."""
    original = allocate_for_model(
        "ultrathink about deadlock root cause",
        "claude-opus-4-7",
        emit=False,
    )
    assert original.tier == "max"
    same = escalate(original, "ultrathink about deadlock root cause", "claude-opus-4-7")
    assert same is original


# ── Reflection ──────────────────────────────────────────────────────────────


def test_reflect_emits_signed_receipt_and_returns_result(tmp_path):
    alloc = allocate_for_model(
        "Design a distributed system",
        "claude-opus-4-7",
        session={"session_id": "refl-1"},
    )

    def fake_reflector(prompt: str, answer: str) -> ReflectionResult:
        return ReflectionResult(
            verdict="revise",
            revision="better answer here",
            findings=["missed the CAP tradeoff"],
            reflector_model="claude-opus-4-7",
            strategy=SELF_STRATEGY,
            duration_ms=1200,
        )

    result = reflect(alloc, "Design a distributed system", "first answer", fake_reflector)

    assert result.verdict == "revise"
    assert result.revision == "better answer here"

    log = tmp_path / "reflection-log.jsonl"
    lines = [json.loads(l) for l in log.read_text().strip().split("\n")]
    assert len(lines) == 1
    rec = lines[0]
    assert verify_record(rec) is True
    assert rec["sid"] == alloc.session_id
    assert rec["tid"] == alloc.turn_id  # reflection pairs with the ORIGINAL turn
    assert rec["payload"]["strategy"] == SELF_STRATEGY
    assert rec["payload"]["verdict"] == "revise"
    assert rec["payload"]["revision_provided"] is True
    assert rec["payload"]["findings_count"] == 1


def test_reflect_ratify_produces_no_revision(tmp_path):
    alloc = allocate_for_model("Design a distributed system", "claude-opus-4-7", emit=False)

    def ratifier(prompt: str, answer: str) -> ReflectionResult:
        return ReflectionResult(verdict="ratify", strategy=DROIDX_STRATEGY)

    result = reflect(alloc, "Design a distributed system", "an answer", ratifier)
    assert result.revision is None
    assert result.verdict == "ratify"


def test_reflect_records_droidx_strategy(tmp_path):
    """When reflector says strategy=droidx, that's what lands in the receipt."""
    alloc = allocate_for_model(
        "Design a distributed system",
        "claude-opus-4-7",
        session={"session_id": "refl-dx-1"},
    )

    def droidx_reflector(prompt: str, answer: str) -> ReflectionResult:
        return ReflectionResult(
            verdict="partial",
            findings=["edge case X missed", "edge case Y missed"],
            reflector_model="opus-4.6-mythos-k3",
            strategy=DROIDX_STRATEGY,
        )

    reflect(alloc, "Design a distributed system", "first answer", droidx_reflector)

    log = tmp_path / "reflection-log.jsonl"
    rec = json.loads(log.read_text().strip().split("\n")[-1])
    assert rec["payload"]["strategy"] == DROIDX_STRATEGY
    assert rec["payload"]["reflector_model"] == "opus-4.6-mythos-k3"
    assert rec["payload"]["verdict"] == "partial"
    assert rec["payload"]["findings_count"] == 2


# ── Overthinking detector ───────────────────────────────────────────────────


def test_overthinking_flags_underused_tier(tmp_path):
    """After 12 heavy turns at 10% utilisation, the detector flags the tier."""
    from praxis.overthinking import detect_overthinking

    # Build 12 paired alloc+outcome records at tier=heavy, 10% utilisation.
    for i in range(12):
        sid = f"ot-sess-{i}"
        allocate_for_model(
            "Design a distributed pipeline",
            "claude-opus-4-7",
            session={"session_id": sid},
        )
        # Hand-write outcome mimicking the outcome hook at 10% util.
        from praxis.receipt import emit_record
        emit_record(
            ledger_name="outcome-log.jsonl",
            record_type="outcome",
            session_id=sid,
            turn_id=1,
            payload={
                "thinking_used": 1638,   # ~10% of 16384
                "input_tokens": 100,
                "output_tokens": 200,
                "cache_read": None,
                "tool_calls": 0,
                "duration_ms": 1000,
                "stop_reason": "end_turn",
            },
        )

    report = detect_overthinking(home=str(tmp_path))
    heavy_finding = next(t for t in report.tiers if t.tier == "heavy")
    assert heavy_finding.underused is True
    assert heavy_finding.n_samples == 12
    assert heavy_finding.recommendation is not None
    assert "medium" in heavy_finding.recommendation  # demotion suggestion


def test_overthinking_silent_below_min_samples(tmp_path):
    """Fewer than MIN_SAMPLES turns per tier: no findings emitted."""
    from praxis.overthinking import detect_overthinking

    for i in range(3):  # only 3 — below the 10-sample floor
        sid = f"ot-small-{i}"
        allocate_for_model("Design X", "claude-opus-4-7", session={"session_id": sid})
        from praxis.receipt import emit_record
        emit_record(
            ledger_name="outcome-log.jsonl",
            record_type="outcome",
            session_id=sid,
            turn_id=1,
            payload={"thinking_used": 100, "stop_reason": "end_turn"},
        )
    report = detect_overthinking(home=str(tmp_path))
    assert len(report.tiers) == 0


def test_overthinking_no_false_positive_on_healthy_tier(tmp_path):
    """Tier at 80%+ utilisation must NOT be flagged."""
    from praxis.overthinking import detect_overthinking

    for i in range(12):
        sid = f"ot-healthy-{i}"
        allocate_for_model(
            "Design a distributed pipeline",
            "claude-opus-4-7",
            session={"session_id": sid},
        )
        from praxis.receipt import emit_record
        emit_record(
            ledger_name="outcome-log.jsonl",
            record_type="outcome",
            session_id=sid,
            turn_id=1,
            payload={"thinking_used": 13500, "stop_reason": "end_turn"},  # ~82% util
        )

    report = detect_overthinking(home=str(tmp_path))
    heavy = next(t for t in report.tiers if t.tier == "heavy")
    assert heavy.underused is False
    assert heavy.recommendation is None


def test_overthinking_report_render_is_nonempty(tmp_path):
    """The .rendered() CLI output must include the tier name and the signal."""
    from praxis.overthinking import detect_overthinking

    for i in range(11):
        sid = f"ot-render-{i}"
        allocate_for_model("Design X", "claude-opus-4-7", session={"session_id": sid})
        from praxis.receipt import emit_record
        emit_record(
            ledger_name="outcome-log.jsonl",
            record_type="outcome",
            session_id=sid,
            turn_id=1,
            payload={"thinking_used": 1000, "stop_reason": "end_turn"},
        )
    report = detect_overthinking(home=str(tmp_path))
    rendered = report.rendered()
    assert "heavy" in rendered
    assert "underused" in rendered


def test_overthinking_ignores_unpaired_allocs(tmp_path):
    """Allocs with no matching outcome must not count toward sample size."""
    from praxis.overthinking import detect_overthinking

    for i in range(15):
        allocate_for_model("Design X", "claude-opus-4-7", session={"session_id": f"unp-{i}"})
        # No outcome emitted.
    report = detect_overthinking(home=str(tmp_path))
    # No tier has enough samples because none of them have outcomes.
    assert len(report.tiers) == 0
