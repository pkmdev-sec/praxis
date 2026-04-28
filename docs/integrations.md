# Integrations: CXR + DroidX

Praxis runs in four places today:

  1. Claude Code hook (`hooks/praxis-allocator.py` + `praxis-outcome.py`)
  2. LangChain / LangGraph (`PraxisBudget` Runnable)
  3. OpenAI Agents SDK (`PraxisRunHooks`)
  4. **CXR + DroidX (recursive + adversarial — the hardest shape)**

This doc covers the fourth. It's the one that proves Praxis is a policy
layer and not just a LangChain wrapper — CXR is recursive, DroidX is
adversarial, and together they test every primitive.

## The integration shape

```
User asks CXR something
  │
  ▼
CXR decides to spawn sub-agents (possibly nested)
  │
  ▼
for each spawn:                    [SPENDING SIDE — Praxis allocates]
  with cxr_praxis_dispatch(msg, model=m, session_id=sid,
                           parent_tid=p, depth=d) as ctx:
      response = real_model_call(msg, effort=ctx.cxr_effort)
      ctx.record_outcome(response)
  │
  ▼
optionally: DroidX reflects          [ATTESTATION SIDE — adversarial]
  reflector = make_budget_aware_reflector(droidx_challenge_fn, ctx.alloc)
  result = reflect(ctx.alloc, msg, response_text, reflector)
  │
  ▼
signed receipts on disk              [TRUST LAYER]
  praxis verify  → 100% verified, 0 tampered
  praxis report  → per-tier regret across the recursion tree
```

Every arrow is a signed receipt. The tree is reconstructable post-hoc.

## CXR adapter

```python
from praxis.adapters.cxr import cxr_praxis_dispatch, make_spawn_extras

def dispatch_spawn(message, *, model, reasoning_effort=None,
                   parent_tid=None, depth=0, spawn_kind="spawn_agent",
                   session_id):
    with cxr_praxis_dispatch(
        message,
        model=model,
        session_id=session_id,
        parent_tid=parent_tid,
        depth=depth,
        spawn_kind=spawn_kind,
        override_effort=reasoning_effort,   # honours caller's choice if given
    ) as ctx:
        response = cxr_call_model(message, effort=ctx.cxr_effort)
        ctx.record_outcome(response)
        return response
```

The integration is **one context manager**. Everything else — receipt
emission, session/turn bookkeeping, effort translation from Praxis's
five-level enum to CXR's three-level one — is handled internally.

## What the ledger looks like

After a root turn with two child spawns:

```
allocation-log.jsonl (3 rows)
  tid=1  alloc     tier=heavy   effort=high    parent=None  kind=main
    tid=2  alloc     tier=light   effort=low     parent=1     kind=rlm_map
    tid=3  alloc     tier=heavy   effort=high    parent=1     kind=rlm_map

outcome-log.jsonl (3 rows)
  tid=1  outcome   thinking_used=14000  stop=end_turn
  tid=2  outcome   thinking_used=5000   stop=end_turn
  tid=3  outcome   thinking_used=5000   stop=end_turn
```

Read top-to-bottom:

1. Root turn asked to design a distributed system → Praxis scored it heavy → effort=high.
2. First child spawned to refactor auth → scored light → effort=low. **Cheap work gets a cheap budget, even inside a heavy-tier session.**
3. Second child spawned to design the event-sourcing pipeline → scored heavy → effort=high. **Non-uniform allocation across siblings.**

The `parent_tid` + `depth` fields make the tree reconstructable. A future
`praxis report --tree` command can walk this as a call graph.

## Effort translation

Praxis uses a five-level effort enum (`low / medium / high / xhigh / max`)
because that's what Anthropic Opus 4.7 accepts. CXR mostly talks to OpenAI-
style APIs with a three-level enum (`low / medium / high`). The adapter
handles the translation:

| Praxis effort | CXR effort |
|---|---|
| `low` | `low` |
| `medium` | `medium` |
| `high` | `high` |
| `xhigh` | `high` (downcast) |
| `max` | `high` (downcast) |

If you need the full range on a provider that supports it, pass
`override_effort="xhigh"` explicitly. The adapter records that as
`decision="caller_override"` in the receipt.

## DroidX as a reflector

DroidX's structured verdicts (`agree / disagree / partial / unreachable`)
map directly onto Praxis's reflection vocabulary (`ratify / revise /
partial / unreachable`). The adapter is essentially a verdict normaliser
plus a budget-aware challenger hint:

```python
from praxis.adapters.droidx import make_budget_aware_reflector
from praxis.reflection import reflect

# Your DroidX client, whatever shape — HTTP, local subprocess, cxr tool call.
def my_droidx_client(**kwargs):
    return droidx_challenge(**kwargs)   # returns {verdict, findings, ...}

# Per-turn reflector, closed over the allocation so it knows the spend.
reflector = make_budget_aware_reflector(
    my_droidx_client,
    praxis_alloc,
    primary_strategy="plan_then_execute",
)

result = reflect(praxis_alloc, prompt, answer, reflector)
# result.verdict  ∈ {"ratify", "revise", "partial", "unreachable"}
# result.revision — DroidX's proposed fix, if any
# result.findings — structured issues list
# Signed reflection receipt emitted to reflection-log.jsonl
```

### Budget-aware challenger selection

When Praxis's primary turn ran at `high / xhigh / max` effort, we hint
to DroidX: *prefer cheap, structurally divergent challengers*
(`symbolic_validate`, `counterfactual`). When the primary was cheap, we
hint the opposite: *spend more on the challenge*
(`debate`, `plan_then_execute`).

The rationale is the "complementary, not inherited" rule. The ensemble
is strictly stronger when the primary and challenger attack the problem
with **different resources**, not more of the same. If you reflect on an
already-expensive max-tier answer with another max-tier call, you
mostly surface the same model's shared priors; if you reflect with a
cheap symbolic check, the error modes are uncorrelated.

### Fallback to self-reflection

DroidX is a **sidecar, not a dependency**. If it's unreachable:

- `droidx_reflector(...)` catches the client exception and returns
  `ReflectionResult(verdict="unreachable", ...)`.
- The signed reflection receipt records the outage
  (`payload.verdict == "unreachable"`).
- Praxis returns the primary response unchanged.

In practice, adapters that want DroidX when available but don't want to
block without it do:

```python
reflector = my_droidx_reflector if droidx_is_running() else None
llm = PraxisBudget(base, reflector=reflector)
# reflector=None → falls back to the built-in self-reflect template
```

## Recursion tree properties

The schema additions (`parent_tid`, `depth`, `spawn_kind`, `source`)
are **strictly additive**. Ledgers from before this work still verify.
Reports that know about the new fields get a tree view; reports that
don't treat the extras as opaque and carry on.

Invariants the adapter guarantees (and tests enforce):

- `depth == 0` receipts have `parent_tid is None`; all other receipts
  do not.
- `tid` monotonically increases within a session.
- Every child `parent_tid` points to a `tid` that exists in the same
  session's ledger.
- An alloc receipt on disk never lies about what ran: if the caller
  passed `override_effort="high"`, the receipt says `effort="high"`
  regardless of what the scorer would have picked.
- A model-call exception inside the context manager **does not emit
  an outcome receipt**. The alloc is already on disk at that point;
  the ledger says "we allocated, we never got an answer," which is
  the truth.

## When NOT to use the CXR adapter

Two cases where the plain `PraxisBudget` Runnable is the better fit:

1. **You're already a LangChain / LangGraph user.** `PraxisBudget` wraps
   `ChatAnthropic` / `ChatOpenAI` directly; the CXR adapter is a lower
   level because it has to accommodate the recursion-tree metadata that
   LangChain doesn't expose.

2. **The session is non-recursive.** If you're calling one model at a
   time with no sub-agent spawns, the extra bookkeeping
   (`parent_tid`, `depth`) is noise. Use `PraxisBudget` directly.

## Summary

CXR is the spending side (it decides what to do; Praxis decides how much
to spend). DroidX is the quality-attestation side (it decides whether
the answer is any good). Praxis owns the trust layer in the middle — one
signed ledger across both, one verify command, one regret report.

All three systems ship. Nothing is required. Every primitive degrades
gracefully when any of the others is missing.
