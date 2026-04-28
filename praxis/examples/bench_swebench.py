"""
Praxis × SWE-bench Verified — end-to-end benchmark runner.

Runs the canonical three-arm Pareto study on real SWE-bench Verified
problems using the real Anthropic SDK. Takes an API key and a few hours;
produces a signed bench ledger.

Setup::

    pip install 'praxis[bench]' anthropic datasets
    export ANTHROPIC_API_KEY=sk-ant-...
    export PRAXIS_HOME=~/praxis-runs/$(date +%Y%m%d)

Run::

    # Smoke test: 3 problems, ~$1 of spend, verifies the pipeline.
    python examples/bench_swebench.py --limit 3 --eval-stub

    # Small run: 20 problems, real evaluator, ~$10.
    python examples/bench_swebench.py --limit 20 --eval-harness my.eval:run

    # Full headline run: all 500 problems × 3 arms, real evaluator.
    python examples/bench_swebench.py --eval-harness my.eval:run

The ``--eval-harness`` argument takes a Python import path
``module:function`` that implements ``(instance, patch) -> {"resolved": bool}``.
Wire this to your preferred SWE-bench runner (swebench.harness, a
container-based evaluator, etc.).

This script is **deliberately minimal** — ~80 lines — because everything
interesting lives in ``praxis.bench.*``. The point is that a real
benchmark run is configuration, not code.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import uuid
from typing import Any, Callable, Dict

from praxis.bench import PolicyArm, run_bench, summarise
from praxis.bench.anthropic_adapter import anthropic_llm
from praxis.bench.swebench import SweBenchInstance, load_from_hf, load_from_jsonl, stub_eval_fn


def _resolve_eval_fn(dotted: str | None) -> Callable[[SweBenchInstance, str], Dict[str, Any]]:
    """Import a ``module:function`` path and return the callable."""
    if not dotted:
        return stub_eval_fn
    if ":" not in dotted:
        raise ValueError(f"--eval-harness must be MODULE:FUNCTION, got {dotted!r}")
    mod_name, fn_name = dotted.split(":", 1)
    mod = importlib.import_module(mod_name)
    return getattr(mod, fn_name)


def _build_arms(model: str, max_tokens: int) -> list[PolicyArm]:
    """The canonical three-arm study, with a live Anthropic callable."""
    # ONE client shared across arms so the Anthropic SDK's rate-limiter is
    # coherent. Each arm sees the same LLM; Praxis just adjusts the request
    # kwargs differently per arm.
    llm = anthropic_llm(model=model, max_tokens=max_tokens)

    from praxis.bench.harness import _honest_only_policy
    return [
        PolicyArm(name="bare",          model=model, llm=llm, praxis_on=False,
                  note="No Praxis; default provider effort."),
        PolicyArm(name="praxis-honest", model=model, llm=llm, praxis_on=True,
                  policy=_honest_only_policy(),
                  note="Scoring + vendor-shape translation. No amplifiers."),
        PolicyArm(name="praxis-full",   model=model, llm=llm, praxis_on=True,
                  note="Default policy: escalate heavy, reflect heavy+max."),
    ]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Run SWE-bench Verified with Praxis Pareto arms.")
    ap.add_argument("--model",     default="claude-sonnet-4-6",
                    help="Anthropic model name (default: claude-sonnet-4-6)")
    ap.add_argument("--max-tokens", type=int, default=8192,
                    help="Per-request max_tokens (not thinking budget)")
    ap.add_argument("--limit",     type=int, default=None,
                    help="Number of SWE-bench instances (None = all 500)")
    ap.add_argument("--jsonl",     default=None,
                    help="Load from a local JSONL dump instead of Hugging Face")
    ap.add_argument("--eval-harness", default=None,
                    help="Import path to the SWE-bench evaluator, e.g. my.mod:run_eval")
    ap.add_argument("--eval-stub", action="store_true",
                    help="Use the stub evaluator (every task fails; smoke only)")
    ap.add_argument("--include-hints", action="store_true",
                    help="Include the instance hints_text in the prompt")
    ap.add_argument("--run-id",    default=None,
                    help="Explicit session id; default: swebench-<uuid8>")
    args = ap.parse_args(argv)

    if args.eval_stub and args.eval_harness:
        ap.error("--eval-stub and --eval-harness are mutually exclusive")
    eval_fn = stub_eval_fn if args.eval_stub else _resolve_eval_fn(args.eval_harness)

    if args.jsonl:
        tasks = list(load_from_jsonl(args.jsonl, limit=args.limit,
                                     scorer_fn=eval_fn, include_hints=args.include_hints))
    else:
        tasks = list(load_from_hf(split="test", limit=args.limit,
                                  scorer_fn=eval_fn, include_hints=args.include_hints))

    if not tasks:
        print("No tasks loaded. Check --limit and dataset availability.", file=sys.stderr)
        return 1

    run_id = args.run_id or f"swebench-{uuid.uuid4().hex[:8]}"
    arms = _build_arms(args.model, args.max_tokens)

    print(f"Praxis × SWE-bench Verified   run_id={run_id}   tasks={len(tasks)}   model={args.model}")
    print(f"Arms: {', '.join(a.name for a in arms)}\n")

    results = run_bench(tasks, arms, run_id=run_id, bench_name="swebench-verified")
    summary = summarise(results)

    print(summary.rendered())

    # Pairwise Pareto headlines — the one-line story we publish.
    print("\n  Pareto comparison:")
    seen = set()
    for a in ("bare", "praxis-honest", "praxis-full"):
        for b in ("bare", "praxis-honest", "praxis-full"):
            if a >= b or (a, b) in seen:
                continue
            seen.add((a, b))
            print(f"    {summary.dominance(a, b)}")

    print(f"\n  Receipts: $PRAXIS_HOME/*-log.jsonl   Verify with: praxis verify")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
