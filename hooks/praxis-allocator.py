#!/usr/bin/env python3
"""
PRAXIS — Thinking Budget Allocator Hook.

UserPromptSubmit hook that analyses the prompt and emits:
  - A Claude Code ``hookSpecificOutput.additionalContext`` line so Claude
    itself sees a factual complexity assessment (not an imperative — factual
    phrasing dodges prompt-injection defences).
  - A top-level result object with ``max_thinking_tokens``, ``effort``,
    ``thinking_config``, ``model``, ``model_family`` for programmatic consumers.
  - A signed ``alloc`` receipt appended to ``allocation-log.jsonl``.

The receipt is the new bit. Together with ``praxis-outcome.py`` (the Stop
hook) it forms the Verification Layer: every allocation decision is
tamper-evidently logged, joinable against the actual outcome, auditable
locally. See ``docs/receipts.md``.

Install in ``~/.claude/settings.json``::

    {
      "hooks": {
        "UserPromptSubmit": [{"command": "python3 ~/praxis/hooks/praxis-allocator.py"}],
        "Stop":             [{"command": "python3 ~/praxis/hooks/praxis-outcome.py"}]
      }
    }
"""

from __future__ import annotations

import json
import os
import re
import sys

from _praxis_lib import (
    emit_record,
    next_turn_id,
    resolve_session_id,
)


# ── Complexity scoring (mirrors complexity-scorer.mjs) ─────────────────────

KEYWORD_TIERS = {
    "simple": {
        "score": 1,
        "patterns": [
            r"\bwhat is\b", r"\bdefine\b", r"\bexplain\b", r"\bhow to\b",
            r"\blist\b", r"\bshow me\b", r"\btell me\b", r"\bwhat does\b",
        ],
    },
    "moderate": {
        "score": 4,
        "patterns": [
            r"\bfix\b", r"\bmodify\b", r"\bchange\b", r"\bupdate\b",
            r"\badd\b", r"\bremove\b", r"\brefactor\b", r"\bimplement\b",
            r"\bcreate\b", r"\bwrite\b", r"\bbug\b", r"\berror\b",
        ],
    },
    "complex": {
        "score": 7,
        "patterns": [
            r"\bdesign\b", r"\barchitect\b", r"\bsystem\b", r"\bscalable\b",
            r"\bmigrat", r"\boptimiz", r"\bperformance\b", r"\bsecurity\b",
            r"\bdistributed\b", r"\bmicroservic", r"\bpipeline\b",
        ],
    },
    "advanced": {
        "score": 9,
        "patterns": [
            r"\bdebug\s+complex", r"\brace\s+condition", r"\bmemory\s+leak",
            r"\bconcurrency", r"\bdeadlock", r"\bmulti.?step",
            r"\broot\s+cause", r"\bintermittent", r"\bnondeterministic",
            r"\bcomplex\s+issue", r"\bfull\s+stack",
        ],
    },
}

BUDGET_TIERS = {
    1: 0, 2: 0,
    3: 2048, 4: 2048,
    5: 8192, 6: 8192,
    7: 16384, 8: 16384,
    9: 32768, 10: 32768,
}

EFFORT_TIERS = {
    1: None, 2: None,
    3: "low", 4: "low",
    5: "medium", 6: "medium",
    7: "high", 8: "high",
    9: "xhigh", 10: "max",
}

THINKING_KEYWORDS = {
    "ultrathink": 32768,
    "megathink": 16384,
    "think": 8192,
}

KEYWORD_TO_SCORE = {
    32768: 10,
    16384: 8,
    8192: 5,
}

TIER_FOR_SCORE = {
    1: "none", 2: "none",
    3: "light", 4: "light",
    5: "medium", 6: "medium",
    7: "heavy", 8: "heavy",
    9: "max", 10: "max",
}

GUIDANCE_BY_SCORE = {
    1: "Praxis complexity assessment: trivial (1/10). Direct answer is appropriate; extended thinking is unlikely to improve quality.",
    2: "Praxis complexity assessment: trivial (2/10). Direct answer is appropriate; extended thinking is unlikely to improve quality.",
    3: "Praxis complexity assessment: low (3/10). Brief reasoning should be sufficient.",
    4: "Praxis complexity assessment: low (4/10). Brief reasoning should be sufficient.",
    5: "Praxis complexity assessment: moderate (5/10). Default reasoning depth is appropriate.",
    6: "Praxis complexity assessment: moderate (6/10). Default reasoning depth is appropriate.",
    7: "Praxis complexity assessment: high (7/10). This task benefits from careful multi-step reasoning.",
    8: "Praxis complexity assessment: high (8/10). This task benefits from careful multi-step reasoning.",
    9: "Praxis complexity assessment: very high (9/10). Deep analysis and consideration of multiple approaches are warranted.",
    10: "Praxis complexity assessment: very high (10/10). Deep analysis and consideration of multiple approaches are warranted.",
}


# ── Model family detection ──────────────────────────────────────────────────

MODEL_FAMILIES = [
    (re.compile(r"^claude-mythos", re.IGNORECASE), "adaptive_only"),
    (re.compile(r"^claude-opus-4-7", re.IGNORECASE), "adaptive_only"),
    (re.compile(r"^claude-opus-4-6", re.IGNORECASE), "adaptive_preferred"),
    (re.compile(r"^claude-sonnet-4-6", re.IGNORECASE), "adaptive_preferred"),
    (re.compile(r"^claude-(opus-4-5|opus-4-1|opus-4\b|sonnet-4-5|sonnet-4\b|haiku-4|sonnet-3-7)", re.IGNORECASE), "manual"),
    (re.compile(r"^claude-haiku-4-5", re.IGNORECASE), "manual"),
]

DEFAULT_MODEL = "claude-sonnet-4-6"


def resolve_model(data: dict) -> str:
    for src in (
        os.environ.get("PRAXIS_MODEL"),
        data.get("model") if isinstance(data, dict) else None,
        (data.get("session") or {}).get("model") if isinstance(data, dict) else None,
        os.environ.get("ANTHROPIC_MODEL"),
    ):
        if src and isinstance(src, str) and src.strip():
            return src.strip()
    return DEFAULT_MODEL


def classify_model_family(model: str) -> str:
    for pattern, family in MODEL_FAMILIES:
        if pattern.search(model):
            return family
    return "adaptive_only"


def build_thinking_config(complexity: int, family: str) -> dict:
    effort = EFFORT_TIERS.get(complexity)
    tokens = BUDGET_TIERS.get(complexity, 8192)

    if family == "adaptive_only":
        if effort is None:
            return {}
        return {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort},
        }

    if family == "adaptive_preferred":
        if effort is None:
            return {"thinking": {"type": "disabled"}}
        return {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort},
            "legacy_budget_tokens": tokens,
        }

    if tokens == 0:
        return {"thinking": {"type": "disabled"}}
    return {"thinking": {"type": "enabled", "budget_tokens": tokens}}


def detect_thinking_keyword(prompt: str):
    lower = prompt.lower()
    if re.search(r"\bultrathink\b", lower):
        return THINKING_KEYWORDS["ultrathink"]
    if re.search(r"\bmegathink\b", lower):
        return THINKING_KEYWORDS["megathink"]
    if re.search(
        r"\bthink\s+(step\s+by\s+step|carefully|through|deeply|hard|harder|critically|systematically|logically)\b",
        lower,
    ):
        return THINKING_KEYWORDS["think"]
    return None


def score_complexity(prompt: str) -> int:
    if not prompt or not isinstance(prompt, str):
        return 1

    highest_score = 1
    for tier_data in KEYWORD_TIERS.values():
        for pattern in tier_data["patterns"]:
            if re.search(pattern, prompt, re.IGNORECASE):
                highest_score = max(highest_score, tier_data["score"])

    word_count = len(prompt.split())
    if word_count > 150:
        highest_score = max(highest_score, 7)
    elif word_count > 80:
        highest_score = max(highest_score, 5)
    elif word_count > 30:
        highest_score = max(highest_score, 3)

    code_blocks = prompt.count("```") // 2
    question_marks = prompt.count("?")
    if code_blocks > 1 or question_marks > 2:
        highest_score = min(10, highest_score + 1)

    return min(10, max(1, highest_score))


def allocate_tokens(complexity: int) -> int:
    return BUDGET_TIERS.get(complexity, 8192)


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print(json.dumps({}))
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON input: {e}"}), file=sys.stderr)
            print(json.dumps({}))
            return

        prompt = data.get("prompt", "") or data.get("message", "") or ""
        if not prompt:
            print(json.dumps({}))
            return

        keyword_tokens = detect_thinking_keyword(prompt)
        if keyword_tokens is not None:
            tokens = keyword_tokens
            complexity = KEYWORD_TO_SCORE.get(keyword_tokens, 5)
            decision = "keyword_override"
        else:
            complexity = score_complexity(prompt)
            tokens = allocate_tokens(complexity)
            decision = "auto_scored"

        model = resolve_model(data)
        family = classify_model_family(model)
        thinking_config = build_thinking_config(complexity, family)
        effort = EFFORT_TIERS.get(complexity)
        tier = TIER_FOR_SCORE.get(complexity, "medium")

        # Identity: stable session id + monotonic turn id. This is the
        # join key ``praxis-outcome.py`` will pair against.
        session_id = resolve_session_id(data)
        turn_id = next_turn_id(session_id)

        emit_record(
            ledger_name="allocation-log.jsonl",
            record_type="alloc",
            session_id=session_id,
            turn_id=turn_id,
            payload={
                "prompt_preview": prompt[:80],
                "prompt_len": len(prompt),
                "complexity": complexity,
                "tier": tier,
                "budget_requested": tokens,
                "effort": effort,
                "model": model,
                "model_family": family,
                "decision": decision,
            },
        )

        # Top-level result — backward compatible with pre-1.1 consumers.
        result = {
            "max_thinking_tokens": tokens,
            "complexity_score": complexity,
            "decision": decision,
            "effort": effort,
            "model": model,
            "model_family": family,
            "thinking_config": thinking_config,
            "session_id": session_id,
            "turn_id": turn_id,
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": GUIDANCE_BY_SCORE.get(complexity, GUIDANCE_BY_SCORE[5]),
            },
        }

        print(
            f"[PRAXIS] sid={session_id[:8]} tid={turn_id} "
            f"complexity={complexity} tier={tier} tokens={tokens} "
            f"effort={effort} model={model} family={family} "
            f"decision={decision}",
            file=sys.stderr,
        )
        print(json.dumps(result))

    except Exception as e:  # pragma: no cover
        print(json.dumps({"error": f"Unexpected error: {e}"}), file=sys.stderr)
        print(json.dumps({}))


if __name__ == "__main__":
    main()
