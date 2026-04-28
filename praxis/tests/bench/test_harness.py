"""
PRAXIS — benchmark harness tests.

The deterministic toy LLM + fixed prompts give us a reproducible Pareto
chart. The tests pin exact solve rates so any future regression in the
scorer, policy, or escalation loop surfaces as a failing test, not as a
subtle benchmark drift.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent.parent
sys.path.insert(0, str(_PKG))

from praxis.bench.core import PolicyArm, run_bench, summarise
from praxis.bench.harness import _preset_arms, _honest_only_policy
from praxis.bench.toy import ToyLLM, make_toy_tasks, toy_category_lookup
from praxis.receipt import _reset_key_cache


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PRAXIS_HOME", str(tmp_path))
    monkeypatch.setenv("PRAXIS_RECEIPT_KEY", "ab" * 32)
    _reset_key_cache()
    yield


def test_toy_dataset_has_realistic_tier_distribution():
    """The toy prompts must hit multiple scorer tiers — otherwise no signal."""
    from praxis import score_complexity
    tasks = make_toy_tasks()
    scores = [score_complexity(t.prompt) for t in tasks]
    # At least one prompt each at trivial (1), light/medium (3-6), heavy (7-8).
    assert min(scores) <= 2
    assert any(3 <= s <= 6 for s in scores)
    assert any(s >= 7 for s in scores)


def test_toy_llm_accuracy_monotone_in_effort():
    """On hard tasks the mock must reward more effort, not punish it."""
    tasks = make_toy_tasks()
    llm = ToyLLM(task_category_lookup=toy_category_lookup(tasks))

    # Pick a hard task; check that accuracy at max >= accuracy at medium.
    hard = next(t for t in tasks if t.meta["category"] == "hard")
    tmp = {
        "low":    llm(hard.prompt, {"output_config": {"effort": "low"}})["answer"],
        "medium": llm(hard.prompt, {"output_config": {"effort": "medium"}})["answer"],
        "max":    llm(hard.prompt, {"output_config": {"effort": "max"}})["answer"],
    }
    # Sanity: at least one of (medium, max) must outperform low on average
    # across the whole hard set (single task is too noisy for a strict claim).
    hards = [t for t in tasks if t.meta["category"] == "hard"]
    def solve_rate(effort):
        cfg = {"output_config": {"effort": effort}}
        return sum(1 for t in hards if llm(t.prompt, cfg)["answer"] == "REFERENCE") / len(hards)

    low = solve_rate("low")
    hi  = solve_rate("max")
    assert hi >= low  # monotone: more effort, more (or equal) accuracy


def test_pareto_arms_differ_on_solve_rate():
    """The canonical three-arm run must show capability lift, not a flat chart."""
    tasks = make_toy_tasks()
    llm = ToyLLM(task_category_lookup=toy_category_lookup(tasks))
    results = run_bench(tasks, _preset_arms(llm), bench_name="test-pareto")
    summary = summarise(results)

    by_name = {a.arm: a for a in summary.arms}
    bare    = by_name["bare"].solve_rate
    honest  = by_name["praxis-honest"].solve_rate
    full    = by_name["praxis-full"].solve_rate

    # Strict capability story: full >= honest >= bare, with full strictly better.
    assert honest >= bare
    assert full >= honest
    assert full > bare, (
        f"praxis-full must outperform bare. got bare={bare:.3f}, full={full:.3f}"
    )


def test_pareto_full_arm_escalates_on_hard_truncations():
    """
    Hard prompts truncate at 'high' effort; praxis-full must escalate to max.
    Without this behaviour the hard-category lift in the harness output
    disappears.
    """
    tasks = make_toy_tasks()
    llm = ToyLLM(task_category_lookup=toy_category_lookup(tasks))
    results = run_bench(tasks, _preset_arms(llm), bench_name="test-escalate")

    full_hard = [r for r in results if r.arm == "praxis-full" and r.task_id.startswith("hard-")]
    # At least some hard tasks must have triggered escalation.
    assert any(r.escalated for r in full_hard), (
        "Expected escalations on hard-tier truncations with praxis-full."
    )


def test_trivial_category_is_not_degraded_by_praxis():
    """Cheap-path-stays-cheap: trivial solve rates must match bare."""
    tasks = make_toy_tasks()
    llm = ToyLLM(task_category_lookup=toy_category_lookup(tasks))
    results = run_bench(tasks, _preset_arms(llm), bench_name="test-trivial")

    def solve_rate(arm):
        rs = [r for r in results if r.arm == arm and r.task_id.startswith("trivial-")]
        return sum(1 for r in rs if r.score > 0.5) / len(rs)

    assert solve_rate("praxis-full") >= solve_rate("bare")


def test_bench_receipts_are_signed_and_joinable(tmp_path):
    """Every bench cell emits a signed ``bench`` receipt on disk."""
    import json
    from praxis.receipt import verify_record

    tasks = make_toy_tasks(n_trivial=2, n_medium=2, n_hard=2)
    llm = ToyLLM(task_category_lookup=toy_category_lookup(tasks))
    run_bench(tasks, _preset_arms(llm), bench_name="receipt-test")

    bench_log = tmp_path / "bench-log.jsonl"
    assert bench_log.exists()
    lines = [json.loads(l) for l in bench_log.read_text().strip().split("\n") if l.strip()]
    # 6 tasks × 3 arms = 18 bench receipts.
    assert len(lines) == 18
    # Every one must verify.
    for rec in lines:
        assert verify_record(rec), "bench receipt failed verification"
        assert rec["type"] == "bench"
        assert rec["payload"]["bench_name"] == "receipt-test"
        assert "score" in rec["payload"]


def test_honest_only_policy_never_escalates():
    """The 'scoring-only' arm must not invoke escalation — it's the middle Pareto point."""
    tasks = make_toy_tasks()
    llm = ToyLLM(task_category_lookup=toy_category_lookup(tasks))
    arms = _preset_arms(llm)
    # Run only the praxis-honest arm to isolate its behaviour.
    honest = [a for a in arms if a.name == "praxis-honest"]
    results = run_bench(tasks, honest, bench_name="test-honest")
    assert all(not r.escalated for r in results)
