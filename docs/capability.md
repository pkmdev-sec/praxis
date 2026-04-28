# The Capability Layer

> **Why Praxis exists in one sentence:** push every reasoning model past its
> own benchmark scores by orchestrating test-time compute per turn, and
> prove you did so with signed receipts.

## The published evidence Praxis stands on

Three papers established the premise. Praxis is the production shape.

| Paper | Result | Why it matters for Praxis |
|---|---|---|
| **Snell et al. 2024**, ["Scaling LLM Test-Time Compute Optimally..."](https://arxiv.org/abs/2408.03314) | Compute-optimal TTS is **>4× more efficient than best-of-N**. A small model + TTS **outperforms a 14× larger model** in regimes where the base has non-trivial success. | Per-turn compute allocation is the lever; model size is secondary. |
| **Brown et al. 2024**, ["Large Language Monkeys"](https://arxiv.org/abs/2407.21787) | On SWE-bench Lite: DeepSeek-Coder-V2 goes from **15.9 % → 56 %** solve rate, 1 → 250 samples. | The weights didn't change. The spend policy did. |
| **Muennighoff et al. 2025**, ["s1: Simple test-time scaling"](https://arxiv.org/abs/2501.19393) | Qwen2.5-32B + budget forcing **exceeds o1-preview by up to 27 %** on MATH/AIME24. | Budget-level control *on a fixed model* crosses model-tier boundaries. |

The rest of the literature (Damani, Ares, Predictive Scheduling, RADAR — see [`academic-landscape.md`](academic-landscape.md)) establishes that **per-instance pre-hoc allocation for coding agents is the unpublished whitespace.** Praxis occupies it.

## The primitives

Every Praxis decision maps to a signed receipt. Each primitive is a Python module and a receipt type.

### 1. Score (the honest floor)

`praxis.complexity.score_complexity(prompt)` → 1-10.

Rule-based, transparent, reproducible from the receipt payload. The scorer
is deliberately *not* overconfident — it produces the best estimate from
surface signals alone. Capability extraction happens *above* this number,
not by inflating it.

Byte-identical to `hooks/praxis-allocator.py::score_complexity` (test-enforced).

### 2. Allocate (the vendor-shape translator)

`praxis.allocator.build_thinking_config(score, family)` → the exact request
shape for the target model:

- `adaptive_only` (Opus 4.7, Mythos): `{thinking:{type:"adaptive"}, output_config:{effort}}`
- `adaptive_preferred` (Opus 4.6, Sonnet 4.6): same plus `legacy_budget_tokens` for safety
- `manual` (Opus 4.5−, Haiku): `{thinking:{type:"enabled", budget_tokens:N}}`

OpenAI, Gemini, and others translate via the LangChain adapter
(`_to_bind_kwargs`). One scorer, five vendor surfaces.

### 3. Escalate (the "don't silently truncate" primitive)

`praxis.escalation.should_escalate(alloc, response, policy)` → bool,
`praxis.escalation.escalate(alloc, prompt, model)` → next-tier `Allocation`.

When the model hits `stop_reason=max_tokens` on a high-stakes turn, we
retry one tier up, bounded by `TierPolicy.max_escalation_hops`. The
escalated turn is a new `alloc` receipt with `decision="escalated"` and
an `extras.escalated_from` link back to the original turn. A paired
`escalation` record records the hop explicitly for tree-view analysis.

Why this matters for capability: truncated outputs are the single most
common reason a "high effort" run delivers "medium" quality. Escalation
guarantees the user pays once and gets a complete answer, instead of
paying twice (once for the truncated draft, once for the manual retry).

### 4. Reflect (the quality-attestation primitive)

`praxis.reflection.reflect(alloc, prompt, answer, reflector)` → `ReflectionResult`.

A `Reflector` is any callable `(prompt, answer) → ReflectionResult`. Two
strategies ship:

- **DroidX** (preferred when available) — an adversarial challenger that
  applies a *structurally different* strategy (e.g. `symbolic_validate`
  while the primary used `plan-then-execute`). Correlated errors are
  minimised by construction.
- **Self-reflection** (fallback) — `praxis.reflection.self_reflect_prompt`
  template: re-prompts the same model with "review your previous answer".
  Always available. Cheaper. Correlated errors are the cost.

Each reflection pass writes a `reflection` receipt with verdict (`ratify` /
`revise` / `partial` / `unreachable`) and the reflector's model/strategy.

### 5. Detect overthinking (the safety counterpart to escalation)

`praxis.overthinking.detect_overthinking()` → `OverthinkingReport`.

For each tier, compute median utilisation (`thinking_used / budget`)
across the last N turns. If a tier is systematically below 25 % with
≥ 10 samples, flag it and recommend demotion.

The detector **never mutates policy silently.** It surfaces a signal;
the user looks at the receipts and decides. Auto-demotion would be the
same failure mode we're trying to make detectable — see the March 2026
Anthropic silent-degradation incident in [`receipts.md`](receipts.md).

## The policy (where "err high" lives)

Praxis is opinionated at the *policy* level, not the scoring level.
Default `Policy` in `praxis/policy.py`:

| Tier | Complexity | Escalate? | Reflect? | Rationale |
|---|---|---|---|---|
| none | 1-2 | no | no | Trivial prompts. Keep the cheap path cheap. |
| light | 3-4 | no | no | Easy edits. Amplifiers cost more than they pay back. |
| medium | 5-6 | no | no | Routine code. Users can opt in per-project. |
| **heavy** | **7-8** | **yes** | **yes** | **Complex design/debug. Truncation is the biggest quality killer; escalation catches it. Reflection catches correlated mistakes.** |
| **max** | **9-10** | no | **yes** | **Hardest prompts. No escalation target; reflection still pays back.** |

Users override per tier:

```python
from praxis import Policy, TierPolicy

policy = Policy().override(
    heavy=TierPolicy(escalate=True, max_escalation_hops=2, reflect=True),
    max=TierPolicy(escalate=False, reflect=True, prefer_droidx_reflector=True),
)
```

## The capability-extraction flow (per turn)

```
User: "Design a distributed pipeline with CQRS"
  │
  ▼
  score_complexity("Design…") → 7 (heavy tier)
  │
  ▼
  allocate → {effort: "high", budget: 16384}  [alloc-receipt #42 signed]
  │
  ▼
  model.invoke(…, effort="high")
  │
  ▼
  [outcome-receipt #42: thinking_used=16384, stop_reason=max_tokens]
  │                                                  ▲
  │                              TRUNCATED ──────────┘
  ▼
  should_escalate? → yes (heavy tier, max_tokens, hop 0 of 1)
  │
  ▼
  escalate → tier=max, effort="max"   [alloc-receipt #43, escalation-receipt #43]
  │
  ▼
  model.invoke(…, effort="max")
  │
  ▼
  [outcome-receipt #43: thinking_used=28000, stop_reason=end_turn]  ✓
  │
  ▼
  policy.heavy.reflect → yes
  │
  ▼
  reflect via DroidX or self        [reflection-receipt #43]
    verdict: ratify / revise / partial
  │
  ▼
  return response (with reflection attached on ``praxis_reflection`` attribute)
```

Every arrow is a signed receipt. `praxis verify` proves the chain is
intact; `praxis report` summarises the regret ledger across thousands of
turns; `praxis overthinking` catches systematic over-allocation.

## CXR + DroidX native integration

CXR and DroidX are the proof points because they're the hardest shape:
recursive sub-agents (CXR) plus an adversarial challenger (DroidX).

### CXR as the spending side

Every `spawn_agent` / `rlm_query` / `rlm_map` is a Praxis turn:

```python
# cxr/tools/spawn.py (sketch)
from praxis import allocate_for_model

def dispatch_spawn(message, *, model, reasoning_effort=None, session):
    if reasoning_effort is None:   # caller didn't override
        alloc = allocate_for_model(
            message, model, session={"session_id": session.id},
            extras={"parent_tid": session.current_tid, "depth": session.depth,
                    "spawn_kind": "spawn_agent"},
        )
        reasoning_effort = cxr_effort(alloc.effort)  # down-cast xhigh/max to high on GPT-5
    # ...dispatch model with reasoning_effort...
    # post-call: emit_outcome(alloc.session_id, alloc.turn_id, ...)
```

Additive schema: `parent_tid`, `depth`, `spawn_kind` go into the
receipt's `extras` field. No schema version bump — `praxis verify` still
verifies uniformly across CXR + Claude-Code + LangChain ledgers.

Recursion-tree view becomes possible once those fields are populated:

```
praxis report --tree
  turn 42 [depth=0, root]       tier=heavy budget=16384 used=9100
    ├─ 43 [depth=1, rlm_map]     tier=light budget=2048  used=1850
    ├─ 44 [depth=1, rlm_map]     tier=light budget=2048  used=2100  ⚠ over-budget
    └─ 47 [depth=1, spawn_agent] tier=max   budget=32768 used=8200  ⚠ 25% util
```

### DroidX as the reflector

DroidX's `challenge()` already returns `{verdict, findings, strategy}` —
that's the `Reflector` interface. A ten-line adapter turns DroidX into a
first-class Praxis reflector:

```python
# praxis/adapters/droidx.py (sketch)
def droidx_reflector(praxis_alloc):
    def _reflect(prompt, answer):
        result = droidx_challenge(
            question=prompt, cxr_answer=answer,
            strategy_used="plan-then-execute",
            praxis_alloc=praxis_alloc,  # router uses alloc.tier to pick complementary strategy
        )
        return ReflectionResult(
            verdict={"agree":"ratify","disagree":"revise","partial":"partial",
                     "unreachable":"unreachable"}[result.verdict],
            revision=result.revision,
            findings=result.findings,
            reflector_model=result.strategy,
            strategy=DROIDX_STRATEGY,
        )
    return _reflect
```

Fallback path (DroidX unreachable): `ReflectionResult(verdict="unreachable")`,
Praxis logs it and returns the primary answer unchanged. No crash.

### Budget-aware challenger routing

DroidX's harness router already picks a strategy *different* from the
primary. With the Praxis alloc in hand, it can also pick one with
complementary *cost* characteristics:

```python
# droidx/harness_router.py (sketch)
def route(question, answer, strategy_used, praxis_alloc=None):
    if praxis_alloc and praxis_alloc["effort"] in ("high", "xhigh", "max"):
        # Primary burned lots of compute — use a cheap, structurally-different check.
        candidates = ["symbolic_validate", "counterfactual"]
    else:
        # Primary was cheap — spend more on deep challenge.
        candidates = ["debate", "plan_then_execute", "counterfactual"]
    return pick(candidates, exclude=[strategy_used])
```

This is the "complementary not inherited" choice from the alignment
discussion: different strategies, different cost profiles, different error
modes. The ensemble is strictly stronger than either model alone.

## Measuring capability lift

The primary empirical artifact Praxis commits to ship is the
**Praxis-on vs Praxis-off Pareto curve** on SWE-bench Verified and Aider
Polyglot. Target claim, unverified until Week 6:

> For `claude-sonnet-4-6`, enabling Praxis's default policy raises
> SWE-bench Verified solve rate from *X %* (bare) to *Y %* (+ escalation
> + reflection), at a cost of *Z %* more thinking tokens. At some (Y, Z),
> Praxis-Sonnet beats bare Opus.

The infrastructure for running this is the receipt ledger plus a
benchmark harness; the claim is falsifiable either way.

Until that chart lands, Praxis claims only what's directly observable
per turn: *"given this prompt and this model, the receipt proves which
compute levers were pulled and what the model consumed."*

## What's next

- **Week 5** — NVIDIA NemoCurator scorer adapter (plug a trained classifier
  in place of the rule-based scorer).
- **Week 6** — SWE-bench Verified + Aider Polyglot Pareto runs. The
  tentpole claim.
- **Optional later** — self-consistency (`sample_k > 1`): sample k answers
  in parallel, keep the majority. Deferred because the cost multiplier is
  multiplicative and we want calibration data before shipping it as a
  default.

## Summary

Praxis is a capability layer. It chooses the right compute tier, escalates
when truncated, reflects when the task is complex, watches for overthinking,
and signs every decision. Cost savings happen. Capability lift is the
point.
