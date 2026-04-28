"""
PRAXIS — benchmark core.

The runner is a single loop:

    for each task t:
        prompt, scorer = t.prompt, t.scorer
        alloc = allocate_for_model(prompt, arm.model, session=run_session)
        answer, usage = arm.llm(prompt, alloc.thinking_config)
        emit_outcome(...)
        # escalation + reflection live inside ``arm.call``, same as the
        # LangChain adapter. The harness doesn't re-implement them.
        score = scorer(t, answer)
        yield BenchResult(task=t, arm=arm, answer=answer, score=score, ...)

Everything else — model spend, receipts, escalation chains — is the
existing Praxis primitives the harness composes.

:class:`PolicyArm` is the unit of comparison. A typical Pareto study runs
3-5 arms: ``bare`` (no Praxis), ``praxis-honest`` (scoring only), and
``praxis-full`` (scoring + escalation + reflection). Each arm produces a
signed ``bench`` receipt so the ledger stays the source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, median
from typing import Any, Callable, Iterable, List, Optional

from ..allocation import allocate_for_model
from ..escalation import should_escalate, escalate
from ..policy import DEFAULT_POLICY, Policy
from ..receipt import emit_record, resolve_session_id, peek_turn_id


__all__ = [
    "Task",
    "BenchResult",
    "PolicyArm",
    "run_bench",
    "summarise",
    "ArmSummary",
    "BenchSummary",
]


# ── Data shapes ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Task:
    """One benchmark task.

    ``scorer(task, answer)`` returns a float in [0, 1] where 1 = pass.
    Keeping the scorer on the task (rather than the arm) makes task-level
    comparability exact: every arm is scored identically.
    """

    id: str
    prompt: str
    reference: Any = None
    scorer: Optional[Callable[["Task", str], float]] = None
    meta: dict = field(default_factory=dict)

    def score(self, answer: str) -> float:
        if self.scorer is None:
            return 0.0
        try:
            return float(self.scorer(self, answer))
        except Exception:  # pragma: no cover - scorer robustness
            return 0.0


@dataclass(frozen=True)
class PolicyArm:
    """One column of the Pareto study.

    ``llm(prompt, thinking_config)`` must return a dict shaped like:
      {"answer": str,
       "thinking_used": int,
       "input_tokens": int,
       "output_tokens": int,
       "stop_reason": "end_turn" | "max_tokens" | ...}

    Practical adapters bridge real SDKs onto this signature; see
    :mod:`praxis.bench.toy` for a deterministic mock.
    """

    name: str
    model: str
    llm: Callable[[str, dict], dict]
    policy: Policy = DEFAULT_POLICY
    praxis_on: bool = True
    note: str = ""


@dataclass
class BenchResult:
    """Outcome of one (task, arm) cell."""

    task_id: str
    arm: str
    answer: str
    score: float
    thinking_used: int
    total_tokens: int
    escalated: bool
    stop_reason: Optional[str] = None


# ── Runner ──────────────────────────────────────────────────────────────────


def _call_with_praxis(
    prompt: str,
    arm: PolicyArm,
    session_id: str,
) -> tuple[str, int, int, bool, Optional[str]]:
    """
    Dispatch one turn under the Praxis policy, with escalation.

    Returns (answer, thinking_used, total_tokens, escalated?, stop_reason).
    The escalation loop mirrors :class:`PraxisBudget.invoke` byte-for-byte
    so the benchmark measures the same path users actually ship.
    """
    alloc = allocate_for_model(prompt, arm.model, session={"session_id": session_id})
    escalated = False
    hop = 0

    resp = arm.llm(prompt, alloc.thinking_config)
    _emit_turn_outcome(alloc.session_id, alloc.turn_id, resp)

    while should_escalate(alloc, _FakeResp(resp.get("stop_reason")), arm.policy, current_hop=hop):
        hop += 1
        escalated = True
        alloc = escalate(
            alloc, prompt, arm.model,
            session={"session_id": session_id},
            current_hop=hop - 1,
        )
        resp = arm.llm(prompt, alloc.thinking_config)
        _emit_turn_outcome(alloc.session_id, alloc.turn_id, resp)

    return (
        resp.get("answer", ""),
        int(resp.get("thinking_used") or 0),
        int(resp.get("input_tokens") or 0) + int(resp.get("output_tokens") or 0),
        escalated,
        resp.get("stop_reason"),
    )


def _call_bare(prompt: str, arm: PolicyArm) -> tuple[str, int, int, bool, Optional[str]]:
    """Single-shot dispatch with no Praxis wrapper — the control arm."""
    resp = arm.llm(prompt, {})  # empty thinking_config → provider default
    return (
        resp.get("answer", ""),
        int(resp.get("thinking_used") or 0),
        int(resp.get("input_tokens") or 0) + int(resp.get("output_tokens") or 0),
        False,
        resp.get("stop_reason"),
    )


class _FakeResp:
    """Minimal object that carries just a ``stop_reason`` for should_escalate."""
    def __init__(self, stop_reason):
        self.stop_reason = stop_reason


def _emit_turn_outcome(sid: str, tid: int, resp: dict) -> None:
    """Write the signed ``outcome`` receipt the regret ledger depends on."""
    emit_record(
        ledger_name="outcome-log.jsonl",
        record_type="outcome",
        session_id=sid,
        turn_id=tid,
        payload={
            "thinking_used": resp.get("thinking_used"),
            "input_tokens": resp.get("input_tokens"),
            "output_tokens": resp.get("output_tokens"),
            "cache_read": None,
            "tool_calls": 0,
            "duration_ms": None,
            "stop_reason": resp.get("stop_reason"),
        },
    )


def run_bench(
    tasks: Iterable[Task],
    arms: Iterable[PolicyArm],
    *,
    run_id: Optional[str] = None,
    bench_name: str = "praxis-bench",
) -> List[BenchResult]:
    """
    Execute one full (tasks × arms) sweep. Emits one ``bench`` receipt per
    (task, arm) cell *in addition to* the turn-level alloc/outcome/escalation
    receipts already written by the primitives. The bench receipt carries
    the final score — the ledger can replay the Pareto chart.
    """
    results: List[BenchResult] = []
    session_id = run_id or f"bench-{bench_name}"

    for task in tasks:
        for arm in arms:
            if arm.praxis_on:
                arm_session = f"{session_id}::{arm.name}::{task.id}"
                answer, thinking, total, escalated, stop = _call_with_praxis(task.prompt, arm, arm_session)
            else:
                answer, thinking, total, escalated, stop = _call_bare(task.prompt, arm)

            score = task.score(answer)
            r = BenchResult(
                task_id=task.id,
                arm=arm.name,
                answer=answer,
                score=score,
                thinking_used=thinking,
                total_tokens=total,
                escalated=escalated,
                stop_reason=stop,
            )
            results.append(r)

            # Bench-level receipt (score + linkage to the per-turn records).
            arm_session_id = f"{session_id}::{arm.name}::{task.id}" if arm.praxis_on else session_id
            # Tie the bench receipt to the last turn id the arm emitted; 0 on bare arms.
            tid = peek_turn_id(arm_session_id) if arm.praxis_on else 0
            if arm.praxis_on and tid == 0:
                tid = 1  # bare-outcome scaffolding; never 0 for praxis arms in practice.
            emit_record(
                ledger_name="bench-log.jsonl",
                record_type="bench",
                session_id=resolve_session_id({"session_id": session_id}),
                turn_id=0,  # bench record doesn't belong to a specific turn; keep tid=0.
                payload={
                    "bench_name": bench_name,
                    "arm": arm.name,
                    "model": arm.model,
                    "task_id": task.id,
                    "score": score,
                    "thinking_used": thinking,
                    "total_tokens": total,
                    "escalated": escalated,
                    "stop_reason": stop,
                    "praxis_on": arm.praxis_on,
                },
            )

    return results


# ── Summariser ──────────────────────────────────────────────────────────────


@dataclass
class ArmSummary:
    """Metrics for one arm across all tasks."""

    arm: str
    n: int
    solve_rate: float             # fraction of tasks with score > 0.5
    mean_score: float
    mean_thinking: float
    total_thinking: int
    mean_total_tokens: float
    escalation_rate: float
    truncation_rate: float        # fraction of final turns whose stop_reason == max_tokens


@dataclass
class BenchSummary:
    """Pareto-ready summary across arms."""

    arms: List[ArmSummary] = field(default_factory=list)

    def dominance(self, a: str, b: str) -> str:
        """
        "a dominates b" / "b dominates a" / "non-dominated" comparison on
        (solve_rate, mean_thinking). Useful as a one-line headline.
        """
        aa = next(x for x in self.arms if x.arm == a)
        bb = next(x for x in self.arms if x.arm == b)
        # a dominates b iff a has better-or-equal score AND less-or-equal spend,
        # strict on at least one dimension.
        if aa.solve_rate >= bb.solve_rate and aa.mean_thinking <= bb.mean_thinking and (
            aa.solve_rate > bb.solve_rate or aa.mean_thinking < bb.mean_thinking
        ):
            return f"{a} dominates {b}"
        if bb.solve_rate >= aa.solve_rate and bb.mean_thinking <= aa.mean_thinking and (
            bb.solve_rate > aa.solve_rate or bb.mean_thinking < aa.mean_thinking
        ):
            return f"{b} dominates {a}"
        return "non-dominated (tradeoff)"

    def rendered(self) -> str:
        """CLI-ready table."""
        lines = ["", "  Praxis benchmark summary", "  " + "─" * 72]
        lines.append("    arm                n    solve%   mean-think   esc%   trunc%")
        lines.append("    " + "─" * 68)
        for a in self.arms:
            lines.append(
                f"    {a.arm:16} {a.n:4}   "
                f"{a.solve_rate*100:6.1f}%   "
                f"{a.mean_thinking:10.0f}   "
                f"{a.escalation_rate*100:5.1f}%  "
                f"{a.truncation_rate*100:5.1f}%"
            )
        lines.append("")
        return "\n".join(lines)


def summarise(results: List[BenchResult]) -> BenchSummary:
    """Compute per-arm summary from the raw result list."""
    by_arm: dict = {}
    for r in results:
        by_arm.setdefault(r.arm, []).append(r)

    arms: List[ArmSummary] = []
    for arm, rs in by_arm.items():
        n = len(rs)
        solves = sum(1 for r in rs if r.score > 0.5)
        thinkings = [r.thinking_used for r in rs]
        totals = [r.total_tokens for r in rs]
        escs = sum(1 for r in rs if r.escalated)
        truncs = sum(1 for r in rs if r.stop_reason == "max_tokens")
        arms.append(ArmSummary(
            arm=arm,
            n=n,
            solve_rate=solves / n if n else 0.0,
            mean_score=mean([r.score for r in rs]) if rs else 0.0,
            mean_thinking=mean(thinkings) if thinkings else 0.0,
            total_thinking=sum(thinkings),
            mean_total_tokens=mean(totals) if totals else 0.0,
            escalation_rate=escs / n if n else 0.0,
            truncation_rate=truncs / n if n else 0.0,
        ))
    return BenchSummary(arms=arms)


# ── Parallel runner ─────────────────────────────────────────────────────────

def run_bench_parallel(
    tasks: Iterable[Task],
    arms: Iterable[PolicyArm],
    *,
    run_id: Optional[str] = None,
    bench_name: str = "praxis-bench",
    max_workers: int = 8,
) -> List[BenchResult]:
    """
    Thread-parallel drop-in for :func:`run_bench`. Same signature plus
    ``max_workers`` — the I/O is HTTPS to a model provider, which the GIL
    doesn't block on, so threads are the right primitive.

    Parallelism is per (task, arm) cell. Cell-level independence:
      - Each praxis-on cell gets its own ``session_id``, so turn-id
        generation doesn't collide across cells.
      - Bare cells share the run's session_id but emit ``tid=0`` on the
        bench receipt (they don't use per-turn allocation).
      - Receipt appends are atomic for our < 4KB lines on POSIX.

    Result ordering is NOT preserved — :func:`summarise` is order-
    independent, so this doesn't matter. If you need deterministic
    ordering for a test, sort the returned list yourself.

    Not used by the deterministic toy harness — serial ``run_bench``
    is faster there because the mock LLM returns in microseconds. This
    is for real SWE-bench runs where each cell takes seconds and a 500-
    instance sweep would otherwise take hours.
    """
    import concurrent.futures as _cf
    tasks_list = list(tasks)
    arms_list = list(arms)
    session_id = run_id or f"bench-{bench_name}"

    cells = [(task, arm) for task in tasks_list for arm in arms_list]

    def _run_cell(cell):
        task, arm = cell
        if arm.praxis_on:
            arm_session = f"{session_id}::{arm.name}::{task.id}"
            answer, thinking, total, escalated, stop = _call_with_praxis(task.prompt, arm, arm_session)
        else:
            answer, thinking, total, escalated, stop = _call_bare(task.prompt, arm)

        score = task.score(answer)
        r = BenchResult(
            task_id=task.id, arm=arm.name, answer=answer, score=score,
            thinking_used=thinking, total_tokens=total, escalated=escalated,
            stop_reason=stop,
        )

        # Bench-level receipt (mirrors run_bench path exactly).
        arm_session_id = f"{session_id}::{arm.name}::{task.id}" if arm.praxis_on else session_id
        tid = peek_turn_id(arm_session_id) if arm.praxis_on else 0
        if arm.praxis_on and tid == 0:
            tid = 1
        emit_record(
            ledger_name="bench-log.jsonl",
            record_type="bench",
            session_id=resolve_session_id({"session_id": session_id}),
            turn_id=0,
            payload={
                "bench_name": bench_name,
                "arm": arm.name,
                "model": arm.model,
                "task_id": task.id,
                "score": score,
                "thinking_used": thinking,
                "total_tokens": total,
                "escalated": escalated,
                "stop_reason": stop,
                "praxis_on": arm.praxis_on,
            },
        )
        return r

    results: List[BenchResult] = []
    with _cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
        for r in pool.map(_run_cell, cells):
            results.append(r)

    return results
