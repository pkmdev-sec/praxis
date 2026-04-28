# Benchmarks: Measuring Capability Lift

The capability-first claim lives or dies on one chart: **solve-rate vs.
thinking-tokens-spent**, with Praxis on and Praxis off. This document
describes the benchmark harness that produces that chart, the
deterministic toy dataset that validates it in CI, and the path to real
SWE-bench Verified / Aider Polyglot runs.

## The three-arm Pareto study

Every Praxis benchmark compares exactly three configurations:

| Arm | Description | What it isolates |
|---|---|---|
| **bare** | No Praxis. Provider default effort. | Baseline: what does a naïve caller get? |
| **praxis-honest** | Scoring + vendor-shape translation. No amplifiers. | Lift from *allocating correctly per prompt* alone. |
| **praxis-full** | Default policy: escalate heavy, reflect heavy + max. | Lift from the full capability stack. |

If `praxis-honest > bare` we've proven scoring matters.
If `praxis-full > praxis-honest` we've proven the amplifiers pay back.
If `praxis-full < bare` the framework is regressing quality and we ship
nothing until we fix it.

## Running the toy dataset

The repo ships a fully deterministic toy benchmark — 24 tasks across
three difficulty categories, a mock LLM with published-curve-shaped
accuracy, and exact solve rates pinned in the test suite.

```bash
cd praxis
python -m praxis.bench.harness
```

Typical output:

```
  Praxis benchmark summary
  ────────────────────────────────────────────────────────────────────────
    arm                n    solve%   mean-think   esc%   trunc%
    ────────────────────────────────────────────────────────────────────
    bare               24     45.8%          512     0.0%    0.0%
    praxis-honest      24     58.3%         6912     0.0%   16.7%
    praxis-full        24     75.0%         9643    16.7%    0.0%

  Per-category breakdown (solve rate):
                        bare     praxis-full   praxis-honest
    trivial             100.0%          100.0%          100.0%
    medium               30.0%           60.0%           60.0%
    hard                  0.0%           66.7%            0.0%
```

Read the hard-category row: **0 % → 66.7 %** solve rate on hard prompts,
driven entirely by escalation catching the `max_tokens` truncation that
bare callers would just lose. That's the capability lift the framework
exists to deliver.

## How the toy dataset embodies the published evidence

`praxis/bench/toy.py` encodes accuracy curves from three papers:

| Category | Base rate | Ceiling | Curve shape | Paper |
|---|---|---|---|---|
| trivial | 95 % | 97 % | flat; extra compute is waste | Snell 2024 (plateau regime) |
| medium  | 35 % | 85 % | +12–15 pt per effort step   | Snell 2024 (sweet spot) |
| hard    |  5 % | 72 % | slow rise, cliff at `max`   | Brown 2024 (SWE-bench Lite shape) |

Additionally, **hard prompts at `high` effort truncate 60 % of the time**
(mirroring the real-world failure mode where a too-small budget on a
complex prompt hits `max_tokens` mid-answer). That's exactly the condition
Praxis's escalation primitive was built for.

The toy is deliberately a fixture, not a prediction. Its job is to let the
test suite pin *exact* solve rates so scorer/policy/escalation regressions
surface as failing tests. It's not evidence of any real model's
performance.

## Writing your own benchmark

Swap the task loader and the LLM callable. Everything else stays.

```python
from praxis.bench import run_bench, summarise, Task, PolicyArm
from langchain_anthropic import ChatAnthropic

def my_tasks():
    # Load SWE-bench, Aider Polyglot, MT-Bench, whatever. One Task per problem.
    for problem in my_dataset:
        yield Task(
            id=problem.id,
            prompt=problem.instruction,
            reference=problem.expected,
            scorer=my_pass_at_k_scorer,
        )

def my_llm(prompt: str, thinking_config: dict) -> dict:
    resp = ChatAnthropic(model="claude-opus-4-7", **_bind(thinking_config)).invoke(prompt)
    return {
        "answer": resp.content,
        "thinking_used": resp.usage_metadata["output_token_details"]["reasoning"],
        "input_tokens":  resp.usage_metadata["input_tokens"],
        "output_tokens": resp.usage_metadata["output_tokens"],
        "stop_reason":   resp.response_metadata.get("stop_reason"),
    }

arms = [
    PolicyArm(name="bare",          model="claude-opus-4-7", llm=my_llm, praxis_on=False),
    PolicyArm(name="praxis-full",   model="claude-opus-4-7", llm=my_llm),  # default policy
]

results = run_bench(list(my_tasks()), arms, bench_name="swe-bench-verified")
print(summarise(results).rendered())
```

Every arm writes signed `bench` receipts to `$PRAXIS_HOME/bench-log.jsonl`,
joinable with the per-turn `alloc` / `outcome` / `escalation` /
`reflection` receipts. One `praxis verify` covers the whole run.

## The real-benchmark path (Week 6)

Three target benchmarks, in priority order:

1. **SWE-bench Verified** — the canonical coding benchmark. 500 problems,
   per-instance pass/fail scoring. Run with `claude-sonnet-4-6` on the
   three arms; target claim is *praxis-full-Sonnet ≥ bare-Opus* at
   comparable spend.

2. **Aider Polyglot** — cross-language code editing. Adds the
   "real diff was applied" signal Swe-bench doesn't capture. Complements
   the Sonnet-vs-Opus story with an Aider-style leaderboard entry.

3. **τ-bench** — tool-use agent benchmark. Tests the orthogonal
   axis: does Praxis hurt or help when most of the work is tool calls
   rather than reasoning?

Each run takes a few hours plus provider cost. Infrastructure: the
harness we just shipped + a per-benchmark Task loader + a real SDK
callable. No harness changes needed.

## What "passes" means

The capability claim is *falsifiable*. Before publishing any numbers:

- **praxis-full solve-rate > praxis-honest > bare**, on every task
  category where compute-scaling applies. If the ordering inverts on
  trivial tasks, that's a policy bug (stop firing amplifiers there).
- **Escalation rate < 25 %**. If more than a quarter of heavy-tier
  turns escalate, the scorer is under-allocating — fix scoring, don't
  paper over it with retries.
- **Mean thinking tokens per solve must improve, not just absolute
  solve rate.** Doubling spend for a single extra solve is a bad deal;
  the Pareto curve has to bend, not just shift.

If any of those fail on SWE-bench Verified, we do not claim a win.
The infrastructure exists so the claim is legible either way.

## Invariants the harness enforces

The benchmark test suite (`praxis/tests/bench/test_harness.py`) pins:

- The toy prompts produce a mix of scorer tiers (not all trivial, not
  all heavy). If the scorer drifts, this test breaks first.
- The mock LLM's accuracy is monotone in effort on hard tasks.
  Non-monotonicity means the toy has drifted out of shape with the
  published curves.
- **praxis-full strictly beats bare** on solve rate, on the toy.
  If we ever ship a change that regresses the capability claim on
  the deterministic toy, CI fails before the change lands.
- Trivial-category solve rate is unchanged by Praxis. The cheap path
  stays cheap.
- Every `bench` receipt verifies under the signing key.
- The `praxis-honest` arm never escalates (it has no amplifiers on).

These are the guardrails that make "capability lift" a testable claim
rather than a slogan.
