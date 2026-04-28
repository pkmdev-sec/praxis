"""
PRAXIS — DroidX adapter tests.

The real DroidX challenger isn't importable or reachable in CI. We stub
the challenge function with a deterministic fake that emits each of the
four possible verdicts, and assert the verdict mapping + budget-aware
strategy selection work correctly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent.parent
sys.path.insert(0, str(_PKG))

from praxis.adapters.droidx import (
    droidx_reflector,
    make_budget_aware_reflector,
    _normalise_verdict,
    _preferred_challengers,
    _CHEAP_CHALLENGERS,
    _DEEP_CHALLENGERS,
)
from praxis.allocation import allocate_for_model
from praxis.reflection import DROIDX_STRATEGY, ReflectionResult
from praxis.receipt import _reset_key_cache


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PRAXIS_HOME", str(tmp_path))
    monkeypatch.setenv("PRAXIS_RECEIPT_KEY", "ab" * 32)
    _reset_key_cache()
    yield


# ── Verdict normalisation ───────────────────────────────────────────────────


def test_verdict_agree_becomes_ratify():
    assert _normalise_verdict("agree") == "ratify"
    assert _normalise_verdict("AGREE") == "ratify"
    assert _normalise_verdict("  agree  ") == "ratify"


def test_verdict_disagree_becomes_revise():
    assert _normalise_verdict("disagree") == "revise"


def test_verdict_partial_passes_through():
    assert _normalise_verdict("partial") == "partial"


def test_verdict_unreachable_passes_through():
    assert _normalise_verdict("unreachable") == "unreachable"


def test_verdict_unknown_falls_back_to_partial():
    """Defensive default so weird DroidX responses don't spuriously claim ratify."""
    assert _normalise_verdict("nonsense") == "partial"
    assert _normalise_verdict(None) == "partial"
    assert _normalise_verdict(42) == "partial"


# ── Budget-aware challenger selection ──────────────────────────────────────


def test_high_effort_primary_prefers_cheap_challengers():
    """When the primary burned lots of compute, use a cheap structural check."""
    assert _preferred_challengers("high") == _CHEAP_CHALLENGERS
    assert _preferred_challengers("xhigh") == _CHEAP_CHALLENGERS
    assert _preferred_challengers("max") == _CHEAP_CHALLENGERS


def test_low_effort_primary_prefers_deep_challengers():
    """When the primary was cheap, spend more on the challenge."""
    assert _preferred_challengers("low") == _DEEP_CHALLENGERS
    assert _preferred_challengers("medium") == _DEEP_CHALLENGERS
    assert _preferred_challengers(None) == _DEEP_CHALLENGERS


# ── Reflector behaviour ────────────────────────────────────────────────────


def _make_stub_droidx(verdict: str, **extras):
    """Build a deterministic DroidX stub that returns a fixed verdict."""
    captured = {}
    def challenge(**kwargs):
        captured.update(kwargs)
        return {"verdict": verdict, **extras}
    challenge.captured = captured  # lets the test inspect what was sent
    return challenge


def test_reflector_agree_produces_ratify_no_revision():
    challenge = _make_stub_droidx("agree")
    reflector = droidx_reflector(challenge)
    result = reflector("Design X", "answer A")

    assert isinstance(result, ReflectionResult)
    assert result.verdict == "ratify"
    assert result.revision is None
    assert result.strategy == DROIDX_STRATEGY


def test_reflector_disagree_includes_revision_when_present():
    challenge = _make_stub_droidx(
        "disagree",
        revision="better answer B",
        findings=["missed the CAP case", "race in step 3"],
        challenger_strategy="symbolic_validate",
    )
    reflector = droidx_reflector(challenge)
    result = reflector("Design X", "answer A")

    assert result.verdict == "revise"
    assert result.revision == "better answer B"
    assert result.findings == ["missed the CAP case", "race in step 3"]
    assert result.reflector_model == "symbolic_validate"


def test_reflector_disagree_without_revision_has_null_revision():
    """Some DroidX strategies produce findings only, no revision."""
    challenge = _make_stub_droidx("disagree", findings=["issue found"])
    reflector = droidx_reflector(challenge)
    result = reflector("Design X", "answer A")
    assert result.verdict == "revise"
    assert result.revision is None


def test_reflector_partial_preserves_findings():
    challenge = _make_stub_droidx(
        "partial",
        findings=["minor issue 1", "minor issue 2"],
    )
    reflector = droidx_reflector(challenge)
    result = reflector("Design X", "answer A")
    assert result.verdict == "partial"
    assert result.revision is None
    assert len(result.findings) == 2


def test_reflector_unreachable_does_not_crash():
    """If DroidX says it can't reach its backend, we must not propagate."""
    challenge = _make_stub_droidx("unreachable")
    reflector = droidx_reflector(challenge)
    result = reflector("Design X", "answer A")
    assert result.verdict == "unreachable"
    assert result.strategy == DROIDX_STRATEGY


def test_reflector_surfaces_client_exception_as_unreachable():
    """A thrown exception must land as verdict=unreachable, not a crash."""
    def boom(**kwargs):
        raise RuntimeError("droidx proxy connection refused")
    reflector = droidx_reflector(boom)
    result = reflector("Design X", "answer A")
    assert result.verdict == "unreachable"
    assert any("droidx proxy connection refused" in f for f in result.findings or [])


def test_reflector_sends_primary_strategy_and_preferred_challengers():
    """The DroidX client must see our strategy + preferred-challengers hints."""
    challenge = _make_stub_droidx("agree")
    reflector = droidx_reflector(challenge, primary_strategy="plan_then_execute")
    reflector("Design X", "answer A")

    assert challenge.captured["strategy_used"] == "plan_then_execute"
    # Default path (no Allocation bound) uses DEEP challengers.
    assert challenge.captured["preferred_challengers"] == _DEEP_CHALLENGERS


def test_budget_aware_reflector_picks_cheap_when_primary_was_heavy(tmp_path):
    """With a heavy/max alloc, the DroidX hint must request cheap challengers."""
    alloc = allocate_for_model(
        "Design a distributed pipeline with CQRS",
        "claude-opus-4-7",
        emit=False,
    )
    assert alloc.tier == "heavy"
    assert alloc.effort == "high"

    challenge = _make_stub_droidx("agree")
    reflector = make_budget_aware_reflector(challenge, alloc)
    reflector(alloc.prompt_preview, "answer")

    assert challenge.captured["preferred_challengers"] == _CHEAP_CHALLENGERS


def test_budget_aware_reflector_picks_deep_when_primary_was_light(tmp_path):
    """A light alloc pairs with a deeper challenger — the cheap path isn't cheap enough."""
    alloc = allocate_for_model(
        "What is git?",
        "claude-opus-4-7",
        emit=False,
    )
    # Trivial prompt → effort None (or low). Either way not high+.
    challenge = _make_stub_droidx("agree")
    reflector = make_budget_aware_reflector(challenge, alloc)
    reflector("What is git?", "answer")

    assert challenge.captured["preferred_challengers"] == _DEEP_CHALLENGERS
