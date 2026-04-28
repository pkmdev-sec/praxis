#!/usr/bin/env python3
"""
PRAXIS — Thinking Budget Allocator Hook
UserPromptSubmit hook that analyzes the prompt and sets optimal reasoning budget.

Install in Claude Code settings:
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "command": "python3 ~/praxis/hooks/praxis-allocator.py"
      }
    ]
  }
}

The hook reads the prompt from stdin (JSON), analyzes complexity, and outputs the
recommended reasoning budget in the shape the *target Claude model* accepts:

- Claude Opus 4.7 and Mythos Preview → adaptive thinking with `effort` enum.
  Manual `thinking.budget_tokens` returns a 400 error on these models.
- Claude Opus 4.6 / Sonnet 4.6 → adaptive thinking with `effort` (preferred),
  `budget_tokens` still accepted but deprecated.
- Claude Opus 4.5 and earlier → manual thinking with `budget_tokens` integer.

Model resolution order (first non-empty wins):
  1. ``$PRAXIS_MODEL`` (explicit override; use for CI/testing)
  2. stdin JSON ``model`` field (Claude Code supplies this when available)
  3. ``$ANTHROPIC_MODEL`` env var
  4. Default: ``claude-sonnet-4-6``

Backward compatibility: the ``max_thinking_tokens`` field is always emitted so
existing consumers continue to work. New fields (``effort``, ``thinking_config``,
``model_family``) are additive.

Claude Code integration: when invoked as a ``UserPromptSubmit`` hook, Claude Code
only acts on documented fields from ``hookSpecificOutput``
(https://docs.claude.com/en/docs/claude-code/hooks — "UserPromptSubmit decision
control"). The allocator therefore emits a JSON document whose top level carries
``hookSpecificOutput.additionalContext`` phrased as a *factual* complexity
assessment. Imperative system-style phrasing ("USE LOW EFFORT") can trigger
Claude's prompt-injection defenses; factual phrasing is explicitly endorsed by the
adaptive-thinking docs ("Tuning thinking behavior" section) at
https://docs.anthropic.com/en/docs/build-with-claude/adaptive-thinking.

Legacy fields (``max_thinking_tokens``, ``complexity_score``, ``decision``,
``effort``, ``model``, ``model_family``, ``thinking_config``) remain at the top
level so Praxis's programmatic API consumers and the JavaScript companion
libraries under ``lib/`` keep working without modification.
"""

import json
import re
import sys
import os
import time

# ── Complexity scoring (mirrors complexity-scorer.mjs) ──

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

# Anthropic `effort` enum (https://docs.anthropic.com/en/docs/build-with-claude/effort).
# Sentinel ``None`` at scores 1–2 means "skip thinking entirely". On Opus 4.7
# this is expressed by omitting ``thinking`` from the request; on Opus 4.5-style
# manual thinking it maps to ``budget_tokens=0``.
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

# Keyword → complexity mapping so effort and budget stay in sync on overrides.
KEYWORD_TO_SCORE = {
    32768: 10,
    16384: 8,
    8192: 5,
}

# Factual per-tier guidance strings injected into the conversation via
# ``hookSpecificOutput.additionalContext``. Phrased as assessments, not
# imperatives, to avoid tripping Claude's prompt-injection defenses
# (see PostToolBatch docs in the Claude Code hooks reference).
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


# ── Model family detection ─────────────────────────────────────────────────

# Classes of thinking API shape, keyed by model family.
# ``adaptive_only``: only ``thinking: {type: "adaptive"}`` + ``effort`` accepted;
#                    manual ``thinking.budget_tokens`` returns 400.
# ``adaptive_preferred``: both shapes accepted; ``effort`` is recommended,
#                        ``budget_tokens`` is deprecated.
# ``manual``: only ``thinking: {type: "enabled", budget_tokens: N}`` is supported.
MODEL_FAMILIES = [
    # Most specific patterns first.
    (re.compile(r"^claude-mythos", re.IGNORECASE), "adaptive_only"),
    (re.compile(r"^claude-opus-4-7", re.IGNORECASE), "adaptive_only"),
    (re.compile(r"^claude-opus-4-6", re.IGNORECASE), "adaptive_preferred"),
    (re.compile(r"^claude-sonnet-4-6", re.IGNORECASE), "adaptive_preferred"),
    (re.compile(r"^claude-(opus-4-5|opus-4-1|opus-4\b|sonnet-4-5|sonnet-4\b|haiku-4|sonnet-3-7)", re.IGNORECASE), "manual"),
    # Haiku 4.5 does not support extended thinking; treat as manual with 0-tokens.
    (re.compile(r"^claude-haiku-4-5", re.IGNORECASE), "manual"),
]

DEFAULT_MODEL = "claude-sonnet-4-6"


def resolve_model(data: dict) -> str:
    """Resolve target model from override env, stdin payload, or default."""
    for src in (
        os.environ.get("PRAXIS_MODEL"),
        data.get("model") if isinstance(data, dict) else None,
        # Claude Code sometimes nests the model under session metadata.
        (data.get("session") or {}).get("model") if isinstance(data, dict) else None,
        os.environ.get("ANTHROPIC_MODEL"),
    ):
        if src and isinstance(src, str) and src.strip():
            return src.strip()
    return DEFAULT_MODEL


def classify_model_family(model: str) -> str:
    """Classify model into one of {adaptive_only, adaptive_preferred, manual}."""
    for pattern, family in MODEL_FAMILIES:
        if pattern.search(model):
            return family
    # Unknown model → assume the newest adaptive-only contract so we don't
    # accidentally send deprecated fields to a future model.
    return "adaptive_only"


def build_thinking_config(complexity: int, family: str) -> dict:
    """
    Build the provider-specific thinking config for a given complexity score
    and model family. Returned dict maps directly to Anthropic request fields.

    Shape examples:
        adaptive_only        → {"thinking": {"type": "adaptive"},
                                "output_config": {"effort": "high"}}
        adaptive_preferred   → {"thinking": {"type": "adaptive"},
                                "output_config": {"effort": "medium"},
                                "legacy_budget_tokens": 8192}
        manual               → {"thinking": {"type": "enabled",
                                             "budget_tokens": 8192}}
    """
    effort = EFFORT_TIERS.get(complexity)
    tokens = BUDGET_TIERS.get(complexity, 8192)

    if family == "adaptive_only":
        # Skip thinking for trivial prompts by omitting the config entirely;
        # the caller can detect ``"thinking" not in cfg`` and drop the field.
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
            # Deprecated but still accepted on Opus 4.6 / Sonnet 4.6; emitted
            # for belt-and-suspenders clients that haven't migrated yet.
            "legacy_budget_tokens": tokens,
        }

    # manual
    if tokens == 0:
        return {"thinking": {"type": "disabled"}}
    return {"thinking": {"type": "enabled", "budget_tokens": tokens}}


def detect_thinking_keyword(prompt: str):
    """
    Check if the prompt already contains a thinking keyword.

    Uses more specific patterns for 'think' to avoid false positives with
    natural language (e.g., "I need to think about this").
    """
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
    """Score prompt complexity from 1-10."""
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
    """Map complexity score to thinking token budget."""
    return BUDGET_TIERS.get(complexity, 8192)


def log_allocation(prompt_preview: str, complexity: int, tokens: int,
                   effort, model: str, family: str) -> None:
    """Log the allocation decision to a file for tracking."""
    log_dir = os.path.expanduser("~/praxis/assets")
    log_file = os.path.join(log_dir, "allocation-log.jsonl")
    try:
        os.makedirs(log_dir, exist_ok=True)
        entry = json.dumps({
            "prompt_preview": prompt_preview[:80],
            "complexity": complexity,
            "tokens": tokens,
            "effort": effort,
            "model": model,
            "model_family": family,
            "timestamp": time.time(),
        })
        with open(log_file, "a") as f:
            f.write(entry + "\n")
    except OSError:
        pass  # Non-critical logging failure


def main():
    """Main hook entry point."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print(json.dumps({}))
            return

        data = json.loads(raw)
        prompt = data.get("prompt", "") or data.get("message", "") or ""

        if not prompt:
            print(json.dumps({}))
            return

        # Check for explicit thinking keywords first.
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

        log_allocation(prompt, complexity, tokens, effort, model, family)

        # Preserve existing fields for backward compatibility with Praxis's
        # programmatic API and the JavaScript helpers in ``lib/``.
        result = {
            "max_thinking_tokens": tokens,
            "complexity_score": complexity,
            "decision": decision,
            # Additive fields that describe the allocation at the Anthropic
            # API level (model-aware).
            "effort": effort,
            "model": model,
            "model_family": family,
            "thinking_config": thinking_config,
            # Claude Code-recognised UserPromptSubmit field. This is the *only*
            # top-level key Claude Code actually acts on. Phrased as a factual
            # assessment (not an imperative) per the adaptive-thinking docs.
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": GUIDANCE_BY_SCORE.get(complexity, GUIDANCE_BY_SCORE[5]),
            },
        }

        print(
            f"[PRAXIS] complexity={complexity} tokens={tokens} "
            f"effort={effort} model={model} family={family} "
            f"decision={decision}",
            file=sys.stderr,
        )

        print(json.dumps(result))

    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON input: {str(e)}"}), file=sys.stderr)
        print(json.dumps({}))
    except Exception as e:
        print(json.dumps({"error": f"Unexpected error: {str(e)}"}), file=sys.stderr)
        print(json.dumps({}))


if __name__ == "__main__":
    main()
