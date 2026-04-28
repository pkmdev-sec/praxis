"""
PRAXIS — benchmark harness.

Runs the capability-on vs capability-off comparison that produces the
Pareto curve the capability-first claim rests on.

Public surface:
  - :class:`Task`, :class:`BenchResult`, :class:`PolicyArm` — data shapes.
  - :func:`run_bench` — execute one (tasks × policy arm) run, emit receipts.
  - :func:`summarise` — compute per-arm metrics + Pareto summary.
  - :mod:`praxis.bench.harness` — assembled CLI entry point.
  - :mod:`praxis.bench.toy` — deterministic mock tasks + mock LLM for CI.

The harness is intentionally small and SDK-agnostic. Real benchmarks
(SWE-bench Verified, Aider Polyglot) drop in by swapping the Task loader
and the LLM callable — no harness changes required.
"""

from .core import (
    Task,
    BenchResult,
    PolicyArm,
    run_bench,
    run_bench_parallel,
    summarise,
    ArmSummary,
    BenchSummary,
)

__all__ = [
    "Task",
    "BenchResult",
    "PolicyArm",
    "run_bench",
    "run_bench_parallel",
    "summarise",
    "ArmSummary",
    "BenchSummary",
]
