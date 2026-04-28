"""
PRAXIS — Overthinking detector.

The capability-first framing ("err high, escalate when truncated, reflect
when complex") burns tokens on easy prompts if we're not careful. This
module is the safety counterpart to :mod:`praxis.escalation`: it watches
outcome history and suggests a **tier demotion** when the model is
systematically under-using its budget.

The detection rule is deliberately simple and statistically honest:

  For each tier, look at the last N outcomes. If the *median utilisation*
  (``thinking_used / budget_requested``) is below ``UNDERUSE_THRESHOLD``
  across at least ``MIN_SAMPLES`` turns, recommend demoting prompts at
  that tier by one rung.

The detector **does not mutate policy silently**. It returns a
:class:`OverthinkingReport` that the caller — `bin/praxis report` or a
manual CLI command — shows to the user. Auto-demotion is an
opt-in future step; today we surface the signal and let a human decide.

Rationale for not auto-demoting:
  - The academic overthinking literature (2604.10739, 2604.06787) shows
    the crossover point is task-dependent. A 30-sample window won't
    always be enough to pick it cleanly.
  - Silent demotion is exactly the failure mode Anthropic's March 2026
    incident taught us to mistrust.
  - Surfacing the signal lets the user look at the prompts in their
    ledger and decide whether those were genuinely easy or the scorer
    just happened to over-allocate that batch.

Over time, with enough ledgers, we'll graduate demotion from a signal
to a default action — but only after the Week 6 SWE-bench data proves
it doesn't regress capability.
"""

from __future__ import annotations

import json
import os
import statistics
from dataclasses import dataclass, field
from typing import List, Optional

from .receipt import ledger_path, verify_record

__all__ = [
    "OverthinkingReport",
    "TierFinding",
    "detect_overthinking",
    "UNDERUSE_THRESHOLD",
    "MIN_SAMPLES",
]


# Median utilisation below this fraction across MIN_SAMPLES outcomes is
# flagged. 0.25 is intentionally generous — less than a quarter of the
# budget consumed means the thinker had lots of headroom; the tier is
# almost certainly over-allocated for this workload.
UNDERUSE_THRESHOLD = 0.25

# Minimum outcomes per tier before we report. Fewer samples are too
# noisy to act on.
MIN_SAMPLES = 10


@dataclass
class TierFinding:
    """Per-tier statistical summary of utilisation."""

    tier: str
    n_samples: int
    median_util: float
    p75_util: float
    underused: bool
    recommendation: Optional[str] = None


@dataclass
class OverthinkingReport:
    """What :func:`detect_overthinking` returns."""

    tiers: List[TierFinding] = field(default_factory=list)
    total_samples: int = 0

    @property
    def any_underused(self) -> bool:
        return any(t.underused for t in self.tiers)

    def rendered(self) -> str:
        """Human-readable table, for CLI display."""
        if not self.tiers:
            return "overthinking: not enough data (need {} outcomes per tier).".format(MIN_SAMPLES)
        lines = ["", "  Overthinking report", "  " + "─" * 56]
        lines.append("    tier      n     p50-util   p75-util   signal")
        lines.append("    " + "─" * 52)
        for t in self.tiers:
            signal = "⚠ underused" if t.underused else "   ok"
            lines.append(
                f"    {t.tier:7} {t.n_samples:4}   "
                f"{t.median_util:8.1%}   {t.p75_util:8.1%}   {signal}"
            )
            if t.recommendation:
                lines.append(f"      → {t.recommendation}")
        lines.append("")
        return "\n".join(lines)


def _read_signed(path: str) -> List[dict]:
    """Read a JSONL ledger, dropping rows that fail signature verification."""
    if not os.path.exists(path):
        return []
    out: List[dict] = []
    for raw in open(path, "r", encoding="utf-8"):
        line = raw.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if verify_record(rec):
            out.append(rec)
    return out


def _pair_outcomes(allocs: List[dict], outcomes: List[dict]) -> List[tuple]:
    """Return a list of ``(alloc_payload, outcome_payload)`` tuples."""
    idx = {(o["sid"], o["tid"]): o for o in outcomes}
    paired = []
    for a in allocs:
        key = (a["sid"], a["tid"])
        if key in idx:
            paired.append((a["payload"], idx[key]["payload"]))
    return paired


def detect_overthinking(
    *,
    min_samples: int = MIN_SAMPLES,
    threshold: float = UNDERUSE_THRESHOLD,
    home: Optional[str] = None,
) -> OverthinkingReport:
    """
    Inspect the current ledger and flag tiers whose median utilisation is
    below ``threshold``.

    ``home`` overrides ``$PRAXIS_HOME`` for testing.
    """
    alloc_file = os.path.join(home, "allocation-log.jsonl") if home else ledger_path("allocation-log.jsonl")
    outcome_file = os.path.join(home, "outcome-log.jsonl") if home else ledger_path("outcome-log.jsonl")

    allocs = _read_signed(alloc_file)
    outcomes = _read_signed(outcome_file)
    pairs = _pair_outcomes(allocs, outcomes)

    # Group utilisation ratios by tier.
    by_tier: dict = {}
    for alloc_p, outcome_p in pairs:
        tier = alloc_p.get("tier")
        budget = alloc_p.get("budget_requested") or alloc_p.get("tokens")
        used = outcome_p.get("thinking_used")
        if not tier or not isinstance(budget, (int, float)) or budget <= 0:
            continue
        if not isinstance(used, (int, float)):
            continue
        ratio = used / budget
        by_tier.setdefault(tier, []).append(ratio)

    findings: List[TierFinding] = []
    for tier, ratios in sorted(by_tier.items(), key=lambda x: _tier_order(x[0])):
        if len(ratios) < min_samples:
            continue
        med = statistics.median(ratios)
        p75 = statistics.quantiles(ratios, n=4)[2] if len(ratios) >= 4 else max(ratios)
        underused = med < threshold
        rec = None
        if underused:
            lower = _tier_below(tier)
            rec = (
                f"median {med:.0%} of budget used across {len(ratios)} turns — "
                f"consider demoting to '{lower}'." if lower else
                f"median {med:.0%} of budget used across {len(ratios)} turns — already at floor."
            )
        findings.append(
            TierFinding(
                tier=tier,
                n_samples=len(ratios),
                median_util=med,
                p75_util=p75,
                underused=underused,
                recommendation=rec,
            )
        )

    return OverthinkingReport(tiers=findings, total_samples=sum(len(v) for v in by_tier.values()))


_TIER_ORDER = {"none": 0, "light": 1, "medium": 2, "heavy": 3, "max": 4}


def _tier_order(tier: str) -> int:
    return _TIER_ORDER.get(tier, 99)


def _tier_below(tier: str) -> Optional[str]:
    order = ["none", "light", "medium", "heavy", "max"]
    try:
        idx = order.index(tier)
    except ValueError:
        return None
    return order[idx - 1] if idx > 0 else None
