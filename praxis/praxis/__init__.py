"""
PRAXIS — reasoning-budget policy framework.

Python package that mirrors the ``lib/*.mjs`` Node modules and the
``hooks/*.py`` Claude Code hooks. Provides:

  - :func:`score_complexity` — 1-10 rule-based prompt scorer.
  - :func:`allocate` / :func:`build_thinking_config` — score → tier → vendor
    request shape, with adaptive/manual/effort branching per model family.
  - :func:`sign_record` / :func:`verify_record` — HMAC-signed "receipt"
    envelope, byte-identical to ``lib/receipt.mjs``.
  - :mod:`praxis.adapters` — framework integrations (LangChain, OpenAI
    Agents, LangGraph nodes, …).

Design contract: **this package is policy, not plumbing**. Every adapter is
a ~50-line wrapper that reads the prompt, calls :func:`allocate`, emits
signed receipts via :func:`emit_record`, and mutates the outgoing request
with the result. The scoring and tier logic live here once, so the behaviour
across Claude Code, LangChain, OpenAI Agents, and LangGraph is identical.
"""

from __future__ import annotations

from .complexity import (
    score_complexity,
    extract_signals,
    classify_task_type,
)
from .allocator import (
    EFFORT_TIERS,
    BUDGET_TIERS,
    TIER_FOR_SCORE,
    allocate,
    build_thinking_config,
    classify_model_family,
    DEFAULT_MODEL,
)
from .receipt import (
    SCHEMA_VERSION,
    POLICY_VERSION,
    sign_record,
    verify_record,
    emit_record,
    resolve_session_id,
    next_turn_id,
    peek_turn_id,
    praxis_home,
    ledger_path,
)
from .allocation import Allocation, allocate_for_model
from .policy import Policy, TierPolicy, DEFAULT_POLICY
from .escalation import should_escalate, escalate, TIER_LADDER
from .overthinking import OverthinkingReport, TierFinding, detect_overthinking
from .reflection import (
    ReflectionResult,
    Reflector,
    reflect,
    self_reflect_prompt,
    DROIDX_STRATEGY,
    SELF_STRATEGY,
)
from .keywords import (
    THINKING_KEYWORDS,
    KEYWORD_TO_SCORE,
    detect_thinking_keyword,
    keyword_score,
)

from . import bench as bench  # noqa: F401

__version__ = "1.2.0"

__all__ = [
    "__version__",
    # complexity
    "score_complexity",
    "extract_signals",
    "classify_task_type",
    # allocator
    "EFFORT_TIERS",
    "BUDGET_TIERS",
    "TIER_FOR_SCORE",
    "allocate",
    "build_thinking_config",
    "classify_model_family",
    "DEFAULT_MODEL",
    # receipt
    "SCHEMA_VERSION",
    "POLICY_VERSION",
    "sign_record",
    "verify_record",
    "emit_record",
    "resolve_session_id",
    "next_turn_id",
    "peek_turn_id",
    "praxis_home",
    "ledger_path",
    # convenience
    "Allocation",
    "allocate_for_model",
    # keywords
    "THINKING_KEYWORDS",
    "KEYWORD_TO_SCORE",
    "detect_thinking_keyword",
    "keyword_score",
    # capability layer
    "Policy",
    "TierPolicy",
    "DEFAULT_POLICY",
    "should_escalate",
    "escalate",
    "TIER_LADDER",
    "ReflectionResult",
    "Reflector",
    "reflect",
    "self_reflect_prompt",
    "DROIDX_STRATEGY",
    "SELF_STRATEGY",
    # overthinking detector
    "OverthinkingReport",
    "TierFinding",
    "detect_overthinking",
]
