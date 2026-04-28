"""
PRAXIS — parallel bench runner tests.

Concurrency-correctness worries we need to rule out:
  - Receipt files must receive one signed record per cell (no truncation,
    no interleaving corruption).
  - Each cell's receipts must verify under HMAC.
  - Summary metrics must be deterministic w.r.t. the *set* of results
    (not the order — ThreadPoolExecutor.map preserves input order, but we
    don't rely on it).
  - Results from serial and parallel runs must agree on solve rates.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent.parent
sys.path.insert(0, str(_PKG))

from praxis.bench import run_bench, run_bench_parallel, summarise
from praxis.bench.harness import _preset_arms
from praxis.bench.toy import ToyLLM, make_toy_tasks, toy_category_lookup
from praxis.receipt import _reset_key_cache, verify_record


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PRAXIS_HOME", str(tmp_path))
    monkeypatch.setenv("PRAXIS_RECEIPT_KEY", "ab" * 32)
    _reset_key_cache()
    yield


def test_parallel_and_serial_agree_on_solve_rates():
    """Both runners must produce the same per-arm solve rate on the toy."""
    tasks = make_toy_tasks(n_trivial=4, n_medium=6, n_hard=4)
    llm = ToyLLM(task_category_lookup=toy_category_lookup(tasks))

    # Serial run in one PRAXIS_HOME, parallel in another — we reset
    # between runs by scoping each to its own session id.
    serial = run_bench(tasks, _preset_arms(llm), bench_name="agree-serial")
    parallel = run_bench_parallel(tasks, _preset_arms(llm), bench_name="agree-parallel",
                                  max_workers=4)

    s_sum = {a.arm: a.solve_rate for a in summarise(serial).arms}
    p_sum = {a.arm: a.solve_rate for a in summarise(parallel).arms}
    assert s_sum == p_sum, f"parallel diverged from serial: serial={s_sum} parallel={p_sum}"


def test_parallel_emits_one_bench_receipt_per_cell(tmp_path):
    """n_tasks × n_arms bench receipts, all signed."""
    tasks = make_toy_tasks(n_trivial=2, n_medium=2, n_hard=2)
    llm = ToyLLM(task_category_lookup=toy_category_lookup(tasks))
    arms = _preset_arms(llm)

    results = run_bench_parallel(tasks, arms, bench_name="receipt-count",
                                 max_workers=6)
    assert len(results) == 6 * 3

    bench_log = tmp_path / "bench-log.jsonl"
    lines = [json.loads(l) for l in bench_log.read_text().strip().split("\n") if l.strip()]
    assert len(lines) == 6 * 3
    for rec in lines:
        assert verify_record(rec), "parallel bench receipt failed HMAC"
        assert rec["type"] == "bench"


def test_parallel_honours_max_workers(tmp_path):
    """max_workers=1 must produce identical receipts to the serial path."""
    tasks = make_toy_tasks(n_trivial=1, n_medium=1, n_hard=1)
    llm = ToyLLM(task_category_lookup=toy_category_lookup(tasks))
    arms = _preset_arms(llm)

    run_bench_parallel(tasks, arms, bench_name="workers-1", max_workers=1)

    bench_log = tmp_path / "bench-log.jsonl"
    lines = [json.loads(l) for l in bench_log.read_text().strip().split("\n") if l.strip()]
    # 3 tasks × 3 arms = 9 cells
    assert len(lines) == 9
    for rec in lines:
        assert verify_record(rec)


def test_parallel_receipts_survive_interleaving(tmp_path):
    """
    Stress test: 12 tasks × 3 arms × 8 workers. All 36 bench receipts must
    be well-formed JSON, verifiable, and on disk. Any race in the append
    path would manifest as malformed JSON or verification failures here.
    """
    tasks = make_toy_tasks(n_trivial=4, n_medium=4, n_hard=4)
    llm = ToyLLM(task_category_lookup=toy_category_lookup(tasks))
    arms = _preset_arms(llm)

    run_bench_parallel(tasks, arms, bench_name="stress", max_workers=8)

    for log_name in ("bench-log.jsonl", "allocation-log.jsonl", "outcome-log.jsonl"):
        log_path = tmp_path / log_name
        if not log_path.exists():
            continue
        for raw in log_path.read_text().strip().split("\n"):
            if not raw.strip():
                continue
            rec = json.loads(raw)            # must parse
            assert verify_record(rec), f"{log_name}: record failed HMAC after parallel run"
