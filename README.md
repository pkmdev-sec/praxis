![Praxis Banner](assets/banner.svg)

<p align="center">
  <strong>A capability layer for reasoning models. Extract maximum quality per turn — allocate, escalate, reflect, prove.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.2.0-f59e0b?style=flat-square" alt="Version"/>
  <img src="https://img.shields.io/badge/node-%3E%3D18-4338ca?style=flat-square" alt="Node"/>
  <img src="https://img.shields.io/badge/python-%3E%3D3.10-3776ab?style=flat-square" alt="Python"/>
  <img src="https://img.shields.io/badge/license-MIT-818cf8?style=flat-square" alt="License"/>
  <img src="https://img.shields.io/badge/tests-281%20passed-22c55e?style=flat-square" alt="Tests"/>
</p>

---

## The claim

Reasoning models under-perform their own benchmark scores in real workflows — not because the weights are weak, but because the **test-time compute** allocated to each turn is picked once at agent construction and never reconsidered.

Published research (Snell 2024, Brown 2024, Muennighoff 2025) shows that *intelligent per-turn compute allocation lets a smaller model beat a larger one*. On SWE-bench Lite, DeepSeek-Coder-V2 jumps from 15.9 % → 56 % solve rate going from 1 → 250 samples. The weights didn't change. The *spend policy* did.

Praxis is the production shape of that finding.

## What Praxis does

On every turn, Praxis orchestrates the test-time compute levers your model provider exposes:

1. **Score** — read the prompt, produce an honest 1-10 complexity score.
2. **Allocate** — map score → tier → the correct vendor shape (`thinking`, `reasoning_effort`, `thinkingBudget`) for the target model family.
3. **Escalate** — when the model hits `stop_reason=max_tokens` on a high-stakes turn, retry one tier higher, bounded.
4. **Reflect** — after complex turns, run a second pass (DroidX if present, self-reflection if not) and log the verdict.
5. **Detect overthinking** — when a tier is systematically under-using its budget, flag it so the user can tune.
6. **Sign every decision** — each step appends an HMAC-signed receipt to disk. Verifiable locally; tamper-evident. `praxis verify` screams if anything was edited.

The primary output is **more quality per prompt**. Cost predictability is a byproduct.

## Quickstart

```bash
# Python package (adapters for LangChain, OpenAI Agents SDK, LangGraph)
pip install praxis

# Claude Code hook (UserPromptSubmit + Stop)
git clone https://github.com/pkmdev-sec/praxis.git
```

```python
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from praxis.adapters.langchain import PraxisBudget

llm = PraxisBudget(
    ChatAnthropic(model="claude-opus-4-7", max_tokens=4096),
    session_id="my-session",
)

reply = llm.invoke([HumanMessage("Design a distributed fault-tolerant pipeline")])
# Praxis scored it at complexity=7 (heavy), chose effort="high",
# and would have auto-escalated to "max" if max_tokens fired.
```

```bash
praxis report                # per-tier regret + utilisation
praxis overthinking          # tier demotion suggestions
praxis verify                # signed-receipt integrity check
praxis calibrate             # score vs utilisation curve
```

## Adapters

| Surface | Install | Entry point |
|---|---|---|
| Claude Code hook | in-repo | `hooks/praxis-allocator.py` + `praxis-outcome.py` |
| LangChain / LangGraph | `pip install 'praxis[langchain]'` | `PraxisBudget` Runnable, `with_praxis()` |
| OpenAI Agents SDK | `pip install 'praxis[openai-agents]'` | `PraxisRunHooks` |
| Codex CXR / DroidX | (native integration — see [`docs/capability.md`](docs/capability.md)) | allocator hook + reflector protocol |

Every adapter does the same five steps. All share one signed ledger format.

## Capability policy

The scorer is honest. The **policy** is where "err high" lives: which amplifiers fire at which tier. Defaults:

| Tier | Complexity | `effort` | Amplifiers |
|---|---|---|---|
| none | 1-2 | — | — |
| light | 3-4 | low | — |
| medium | 5-6 | medium | — |
| **heavy** | **7-8** | **high** | **escalate on `max_tokens`, reflect** |
| **max** | **9-10** | **xhigh / max** | **reflect** (ceiling, no escalation target) |

Override per tier:

```python
from praxis import Policy, TierPolicy

policy = Policy().override(
    medium=TierPolicy(reflect=True),            # turn reflection on for medium too
    heavy=TierPolicy(escalate=True, max_escalation_hops=2),  # double-escalate
)
llm = PraxisBudget(base, policy=policy)
```

## The receipt

Every decision is a signed JSONL line. Cross-language (Python + Node signers produce byte-identical signatures). No PKI, no server round-trip — just HMAC over canonical JSON.

```json
{
  "v": 1,
  "type": "alloc",
  "sid": "my-session",
  "tid": 42,
  "ts": 1777240100.5,
  "policy_version": "1.2.0",
  "payload": {
    "complexity": 7, "tier": "heavy", "effort": "high",
    "budget_requested": 16384, "model": "claude-opus-4-7",
    "model_family": "adaptive_only", "decision": "auto_scored"
  },
  "sig": "5cf199bbfba9dd…"
}
```

See [`docs/receipts.md`](docs/receipts.md) for the full verification layer story, including the March 2026 Anthropic silent-degradation incident that motivated signing in the first place.

## What's honest

- **Praxis is policy, not plumbing.** The frameworks (LangChain, Agents SDK, LangGraph, CXR) already expose the `thinking` / `reasoning_effort` knob. What they don't ship is a *policy* that decides per prompt. That's Praxis.
- **Scoring is rule-based today.** An optional NVIDIA NemoCurator adapter is on the roadmap for users who want a trained scorer.
- **The benchmark claim ("Praxis-Sonnet ≥ bare-Opus on SWE-bench") is unverified.** Week 6 of the roadmap is the SWE-bench Verified + Aider Polyglot Pareto study. Until that lands, we don't claim it.
- **DroidX integration is a sidecar**, not required. Falls back to single-model self-reflection when absent.
- **Overthinking detection surfaces signals, doesn't mutate policy.** Silent auto-demotion would be the exact failure mode we're trying to make detectable. See [`praxis overthinking`](praxis/praxis/overthinking.py).

## Docs

- [`docs/integrations.md`](docs/integrations.md) — CXR + DroidX native integration
- [`docs/benchmarks.md`](docs/benchmarks.md) — Pareto harness + how to run SWE-bench
- [`docs/capability.md`](docs/capability.md) — the capability-first framing, Praxis primitives, CXR/DroidX integration shape
- [`docs/receipts.md`](docs/receipts.md) — receipt schema, signing, verification
- [`docs/adapters.md`](docs/adapters.md) — framework adapters, how to write your own
- [`docs/academic-landscape.md`](docs/academic-landscape.md) — 35-paper survey of adaptive test-time compute
- [`docs/competitive-landscape.md`](docs/competitive-landscape.md) — why the policy quadrant is empty

## License

MIT.
