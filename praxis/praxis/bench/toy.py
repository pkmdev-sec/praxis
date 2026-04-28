"""
PRAXIS — deterministic toy benchmark.

Not a real LLM. A deterministic model of the **accuracy-vs-compute** curve
published in Snell 2024 / Brown 2024 / Muennighoff 2025, with just enough
structure that the capability primitives (escalation, reflection) show
measurable lift on the "right" tasks and no lift (just cost) on trivial ones.

Three task categories, shaped after the empirical findings:

  - **trivial** — a tiny bump from effort, but accuracy plateaus at the
    base rate almost immediately. Extra compute is pure waste.
  - **medium** — the sweet spot. Each effort step adds a meaningful
    accuracy delta. This is where Snell 2024's "4× efficiency" lives.
  - **hard**   — base rate near zero; even ``high`` effort barely cracks
    the problem; ``max`` (or budget-forced escalation) is what unlocks it.
    Mirrors Brown 2024's SWE-bench Lite scaling story.

The mock LLM's accuracy is **deterministic, keyed by (task, effort)** —
no RNG. That means a benchmark run is fully reproducible and the test
suite can assert exact solve rates. Real SWE-bench Verified would slot
into this harness by swapping ``ToyTaskLoader`` for a real one and the
``ToyLLM.call`` for a real API wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

from .core import Task


__all__ = [
    "ToyLLM",
    "make_toy_tasks",
    "contains_reference_scorer",
]


# ── Accuracy model ──────────────────────────────────────────────────────────

# Effort ladder in increasing order.
_EFFORT_ORDER = ["default", "low", "medium", "high", "xhigh", "max"]
# "default" is what the bare arm sees when it sends an empty thinking_config.
# It behaves identically to "low" — it's not that the model has no effort,
# it's just that the caller isn't telling the API to push.

# Per-category accuracy curves, indexed by effort.
#
# Numbers chosen to match the qualitative shape of the published curves
# while remaining honest toy values — they are not predictions of any real
# model, they're a reproducible fixture the test suite can pin exactly.
#
#   trivial:  base 0.95, flat ceiling at 0.97 — no lift from extra compute
#   medium:   base 0.35, rising +12-15pt per step — Snell's sweet spot
#   hard:     base 0.05, rising slowly, cliff at 'max' — Brown's curve
_ACCURACY_CURVES = {
    "trivial": {"default": 0.95, "low": 0.95, "medium": 0.96, "high": 0.97, "xhigh": 0.97, "max": 0.97},
    "medium":  {"default": 0.35, "low": 0.40, "medium": 0.55, "high": 0.70, "xhigh": 0.80, "max": 0.85},
    "hard":    {"default": 0.05, "low": 0.08, "medium": 0.15, "high": 0.30, "xhigh": 0.55, "max": 0.72},
}

# Thinking-token cost per effort level, linear-ish to match the real pricing.
_COST_BY_EFFORT = {
    "default": 512,
    "low":     2048,
    "medium":  8192,
    "high":    16384,
    "xhigh":   24576,
    "max":     32768,
}

# Max-tokens rate: how often ``heavy`` truncates on hard prompts. This is
# what makes escalation earn its keep on the hard category.
_TRUNCATION_RATE = {
    # effort → fraction of hard tasks that truncate at that effort
    "default": 0.0, "low": 0.0, "medium": 0.0, "high": 0.60, "xhigh": 0.25, "max": 0.0,
}


def _effort_from_config(thinking_config: dict) -> str:
    """Extract the effort level the Praxis layer decided to send."""
    if not thinking_config:
        return "default"
    effort = (thinking_config.get("output_config") or {}).get("effort")
    if isinstance(effort, str):
        return effort
    # Manual family uses budget_tokens; map back to the nearest effort rung.
    thinking = thinking_config.get("thinking") or {}
    budget = thinking.get("budget_tokens") if isinstance(thinking, dict) else None
    if isinstance(budget, (int, float)):
        if budget <= 0:
            return "default"
        if budget <= 2048: return "low"
        if budget <= 8192: return "medium"
        if budget <= 16384: return "high"
        if budget <= 24576: return "xhigh"
        return "max"
    return "default"


import hashlib


def _stable_unit(key: str) -> float:
    """Deterministic unit-interval hash. Stable across Python processes."""
    digest = hashlib.md5(key.encode("utf-8")).digest()
    # First 8 bytes → unsigned int → normalise to [0, 1).
    as_int = int.from_bytes(digest[:8], "big")
    return as_int / (1 << 64)


def _deterministic_solve(task_id: str, category: str, effort: str) -> bool:
    """
    Deterministic 'did the model solve it?' function.

    Maps task_id + effort to a fixed [0,1) hash, compares against the
    per-category accuracy curve. Same inputs → same output, always,
    including across Python processes (unlike the builtin hash()).

    NOTE: the hash is independent of ``effort`` — a given task has a
    fixed "difficulty signature" that the accuracy curve compares against.
    That mirrors real benchmarks: the same SWE-bench problem has a
    consistent solve-probability at each effort level.
    """
    threshold = _ACCURACY_CURVES[category][effort]
    return _stable_unit(f"{task_id}::praxis-toy-salt") < threshold


def _deterministic_truncates(task_id: str, category: str, effort: str) -> bool:
    """True iff the mock LLM hits max_tokens on this (task, effort)."""
    if category != "hard":
        return False
    rate = _TRUNCATION_RATE.get(effort, 0.0)
    if rate <= 0:
        return False
    # Independent salt so truncation and solve aren't correlated.
    return _stable_unit(f"{task_id}::praxis-truncate-salt") < rate


# ── LLM + tasks ─────────────────────────────────────────────────────────────


class ToyLLM:
    """Callable(prompt, thinking_config) → response dict."""

    def __init__(self, task_category_lookup: Callable[[str], str]):
        # The mock needs to know each prompt's category to pick the curve.
        # Real benchmarks don't need this — accuracy is measured by the real
        # scorer on the real answer. The toy cheats because the whole point
        # is to produce a reproducible Pareto curve without an actual model.
        self._category_of = task_category_lookup

    def __call__(self, prompt: str, thinking_config: dict) -> dict:
        category = self._category_of(prompt)
        effort = _effort_from_config(thinking_config)

        solved = _deterministic_solve(prompt, category, effort)
        truncated = _deterministic_truncates(prompt, category, effort)

        if truncated:
            # The answer is partial — score as 0 — but the cost still accrues.
            return {
                "answer": "[TRUNCATED]",
                "thinking_used": _COST_BY_EFFORT[effort],
                "input_tokens": 50,
                "output_tokens": 100,
                "stop_reason": "max_tokens",
            }

        answer = "REFERENCE" if solved else "WRONG"
        return {
            "answer": answer,
            "thinking_used": _COST_BY_EFFORT[effort],
            "input_tokens": 50,
            "output_tokens": 200 if solved else 120,
            "stop_reason": "end_turn",
        }


def contains_reference_scorer(task: Task, answer: str) -> float:
    """1.0 if the answer contains the reference token, else 0.0."""
    ref = str(task.reference or "REFERENCE")
    return 1.0 if ref in answer else 0.0


# Prompt templates chosen so the rule-based scorer lands them at the
# intended tier. The scorer's 1-10 output must align with the accuracy
# curve — otherwise the harness would be testing prompt phrasing, not
# the capability layer.
_TRIVIAL_PROMPTS = [
    "What is a variable?",
    "Define recursion.",
    "Explain what git is.",
    "How to list files.",
    "What does the word 'monad' mean?",
    "Show me a Python hello world.",
    "Tell me the time complexity of binary search.",
    "What is JSON?",
]
_MEDIUM_PROMPTS = [
    "Fix the authentication bug in the login flow.",
    "Refactor the payment module to support async processing.",
    "Add input validation to the registration form with server-side checks.",
    "Update the logging system to use structured JSON output everywhere.",
    "Implement a rate limiter for the API using a token bucket.",
    "Create a database migration for adding audit columns to all tables.",
    "Write a retry decorator with exponential backoff and jitter.",
    "Change the cache TTL strategy to adapt to access patterns.",
    "Remove dead code paths after the deprecation window closes.",
    "Modify the build pipeline to run tests in parallel across shards.",
]
_HARD_PROMPTS = [
    "Design a distributed fault-tolerant microservice architecture with CQRS and event sourcing.",
    "Design a scalable real-time analytics pipeline that handles 1M events/sec with sub-second latency.",
    "Architect a multi-region active-active database migration strategy with zero downtime.",
    "Design a secure, performance-optimised authentication system with device attestation and key rotation.",
    "Design a distributed caching layer with consistent hashing, replication, and automatic failover.",
    "Architect a scalable search infrastructure with sharded indexes and query-time federation.",
]


def make_toy_tasks(n_trivial: int = 8, n_medium: int = 10, n_hard: int = 6) -> List[Task]:
    """
    Build a fresh toy task set whose prompts the real Praxis scorer will
    place at the intended tier. The tasks are a reproducible fixture:
    prompt strings, reference tokens, and categories are all fixed.
    """
    tasks: List[Task] = []
    for i in range(min(n_trivial, len(_TRIVIAL_PROMPTS))):
        prompt = _TRIVIAL_PROMPTS[i]
        tasks.append(Task(
            id=f"trivial-{i}",
            prompt=prompt,
            reference="REFERENCE",
            scorer=contains_reference_scorer,
            meta={"category": "trivial"},
        ))
    for i in range(min(n_medium, len(_MEDIUM_PROMPTS))):
        prompt = _MEDIUM_PROMPTS[i]
        tasks.append(Task(
            id=f"medium-{i}",
            prompt=prompt,
            reference="REFERENCE",
            scorer=contains_reference_scorer,
            meta={"category": "medium"},
        ))
    for i in range(min(n_hard, len(_HARD_PROMPTS))):
        prompt = _HARD_PROMPTS[i]
        tasks.append(Task(
            id=f"hard-{i}",
            prompt=prompt,
            reference="REFERENCE",
            scorer=contains_reference_scorer,
            meta={"category": "hard"},
        ))
    return tasks


def toy_category_lookup(tasks: List[Task]) -> Callable[[str], str]:
    """
    Build a ``prompt → category`` resolver for :class:`ToyLLM`.

    In the toy dataset the prompt *is* the task id, so we just read the
    category off each task's meta. Real benchmarks wouldn't need this shim.
    """
    idx = {t.prompt: t.meta.get("category", "medium") for t in tasks}
    def lookup(prompt: str) -> str:
        return idx.get(prompt, "medium")
    return lookup
