#!/usr/bin/env python3
"""
PRAXIS — Thinking Budget Allocator Hook
UserPromptSubmit hook that analyzes the prompt and sets optimal MAX_THINKING_TOKENS.

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

The hook reads the prompt from stdin (JSON), analyzes complexity,
and outputs the recommended MAX_THINKING_TOKENS setting.
"""

import json
import re
import sys
import os

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

THINKING_KEYWORDS = {
    "ultrathink": 32768,
    "megathink": 16384,
    "think": 8192,
}


def detect_thinking_keyword(prompt: str) -> int | None:
    """Check if the prompt already contains a thinking keyword."""
    lower = prompt.lower()
    for keyword, tokens in THINKING_KEYWORDS.items():
        if re.search(rf"\b{keyword}\b", lower):
            return tokens
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

    # Adjust for length
    word_count = len(prompt.split())
    if word_count > 150:
        highest_score = max(highest_score, 7)
    elif word_count > 80:
        highest_score = max(highest_score, 5)
    elif word_count > 30:
        highest_score = max(highest_score, 3)

    # Adjust for structural complexity
    code_blocks = prompt.count("```") // 2
    question_marks = prompt.count("?")
    if code_blocks > 1 or question_marks > 2:
        highest_score = min(10, highest_score + 1)

    return min(10, max(1, highest_score))


def allocate_tokens(complexity: int) -> int:
    """Map complexity score to thinking token budget."""
    return BUDGET_TIERS.get(complexity, 8192)


def log_allocation(prompt_preview: str, complexity: int, tokens: int) -> None:
    """Log the allocation decision to a file for tracking."""
    log_dir = os.path.expanduser("~/praxis/assets")
    log_file = os.path.join(log_dir, "allocation-log.jsonl")
    try:
        os.makedirs(log_dir, exist_ok=True)
        entry = json.dumps({
            "prompt_preview": prompt_preview[:80],
            "complexity": complexity,
            "tokens": tokens,
            "timestamp": __import__("time").time(),
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
            # No input, output empty to pass through
            print(json.dumps({}))
            return

        data = json.loads(raw)
        prompt = data.get("prompt", "") or data.get("message", "") or ""

        if not prompt:
            print(json.dumps({}))
            return

        # Check for explicit thinking keywords first
        keyword_tokens = detect_thinking_keyword(prompt)
        if keyword_tokens is not None:
            tokens = keyword_tokens
            complexity = 10 if keyword_tokens >= 32768 else 8 if keyword_tokens >= 16384 else 5
        else:
            complexity = score_complexity(prompt)
            tokens = allocate_tokens(complexity)

        # Log the allocation
        log_allocation(prompt, complexity, tokens)

        # Output the result
        result = {
            "max_thinking_tokens": tokens,
            "complexity_score": complexity,
            "decision": "keyword_override" if keyword_tokens else "auto_scored",
        }

        # Print to stderr for visibility in logs
        print(
            f"[PRAXIS] complexity={complexity} tokens={tokens} "
            f"decision={result['decision']}",
            file=sys.stderr,
        )

        # Output JSON result
        print(json.dumps(result))

    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON input"}), file=sys.stderr)
        print(json.dumps({}))
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        print(json.dumps({}))


if __name__ == "__main__":
    main()
