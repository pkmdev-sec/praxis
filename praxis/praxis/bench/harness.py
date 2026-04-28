"""
PRAXIS — benchmark CLI harness.

``python -m praxis.bench.harness`` runs the canonical three-arm comparison
on the deterministic toy dataset:

  - ``bare``            — no Praxis. Provider default effort.
  - ``praxis-honest``   — scoring + vendor-shape translation, no amplifiers.
  - ``praxis-full``     — full capability policy (escalation + reflection).

Emits a Pareto-ready table. Real SWE-bench Verified / Aider Polyglot runs
replace the dataset and LLM callable — no harness changes needed.
"""

from __future__ import annotations

import json
import os
import sys

from .core import PolicyArm, run_bench, summarise
from .toy import ToyLLM, make_toy_tasks, toy_category_lookup


def _preset_arms(llm: ToyLLM) -> list[PolicyArm]:
    """The canonical three-arm Pareto study."""
    return [
        PolicyArm(
            name="bare",
            model="toy-model",
            llm=llm,
            praxis_on=False,
            note="No Praxis. Provider default effort.",
        ),
        PolicyArm(
            name="praxis-honest",
            model="claude-opus-4-7",
            llm=llm,
            praxis_on=True,
            # DEFAULT_POLICY but strip amplifiers — scoring-only.
            policy=_honest_only_policy(),
            note="Scoring + vendor-shape translation, no amplifiers.",
        ),
        PolicyArm(
            name="praxis-full",
            model="claude-opus-4-7",
            llm=llm,
            praxis_on=True,
            note="Default policy: escalate heavy, reflect heavy+max.",
        ),
    ]


def _honest_only_policy():
    """A Policy that allocates intelligently but never escalates or reflects."""
    from ..policy import Policy, TierPolicy
    return Policy.from_dict({
        "none":   {"escalate": False, "reflect": False},
        "light":  {"escalate": False, "reflect": False},
        "medium": {"escalate": False, "reflect": False},
        "heavy":  {"escalate": False, "reflect": False},
        "max":    {"escalate": False, "reflect": False},
    })


def main() -> int:
    tasks = make_toy_tasks()
    llm = ToyLLM(task_category_lookup=toy_category_lookup(tasks))
    arms = _preset_arms(llm)

    results = run_bench(tasks, arms, bench_name="toy-pareto")
    summary = summarise(results)

    # Human-readable table.
    sys.stdout.write(summary.rendered())

    # Pairwise dominance headlines — the one-line story.
    sys.stdout.write("\n  Pareto comparison:\n")
    for a in ("bare", "praxis-honest", "praxis-full"):
        for b in ("bare", "praxis-honest", "praxis-full"):
            if a >= b:
                continue
            sys.stdout.write(f"    {summary.dominance(a, b)}\n")

    sys.stdout.write("\n  Per-category breakdown (solve rate):\n")
    sys.stdout.write(_category_breakdown(results, tasks))
    return 0


def _category_breakdown(results, tasks) -> str:
    """Solve-rate per (category, arm) — the 'where does Praxis actually help?' view."""
    task_cat = {t.id: t.meta.get("category", "medium") for t in tasks}
    by_cat_arm: dict = {}
    for r in results:
        cat = task_cat.get(r.task_id, "unknown")
        by_cat_arm.setdefault((cat, r.arm), []).append(r)

    cats = ["trivial", "medium", "hard"]
    arms = sorted({r.arm for r in results})

    lines = ["    " + " " * 10 + "  ".join(f"{a:>14}" for a in arms)]
    for c in cats:
        row = [f"    {c:<10}"]
        for a in arms:
            rs = by_cat_arm.get((c, a), [])
            if not rs:
                row.append(f"{'—':>14}")
                continue
            solve = sum(1 for r in rs if r.score > 0.5) / len(rs)
            row.append(f"{solve*100:>13.1f}%")
        lines.append("  ".join(row))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
