# praxis

> Reasoning-budget policy framework with signed receipts. Cross-provider
> verification layer for LLM thinking tokens.

```
pip install praxis                     # core
pip install praxis[langchain]          # + LangChain / LangGraph adapters
pip install praxis[openai-agents]      # + OpenAI Agents SDK adapter
```

## What this is

Your provider tells you the model "thought hard." **Praxis** is the
open-source policy layer that:

1. **Decides** how hard, per prompt, based on a transparent 1-10 complexity
   scorer.
2. **Records** every decision as an HMAC-signed receipt on disk.
3. **Closes the loop** by pairing allocations against outcomes (token usage,
   stop reasons, retries) so you find out when your provider's "high effort"
   actually collapsed to low.

Across Claude, GPT, Gemini, and any provider that exposes a reasoning knob.

## Quickstart

```python
from praxis import allocate_for_model

alloc = allocate_for_model(
    "Design a distributed fault-tolerant microservice architecture",
    model="claude-opus-4-7",
)
# alloc.complexity        = 8
# alloc.tier              = "heavy"
# alloc.effort            = "high"
# alloc.thinking_config   = {"thinking": {"type": "adaptive"},
#                            "output_config": {"effort": "high"}}
# alloc.turn_id           = 42
# (signed receipt appended to $PRAXIS_HOME/allocation-log.jsonl)
```

## Adapters

- `praxis.adapters.langchain` — drop-in `PraxisBudgetRunnable` that wraps any
  `ChatAnthropic` / `ChatOpenAI` / `ChatVertexAI`.
- `praxis.adapters.openai_agents` — `PraxisRunHooks` for the OpenAI Agents
  SDK that adjusts `ModelSettings.reasoning.effort` per turn.
- (Coming) `praxis.adapters.langgraph` — node pre-hook.

## Verify your ledger

The policy is useless if the numbers can be edited after the fact. Every
record is HMAC-signed with a key under `$PRAXIS_HOME/receipt.key`:

```bash
praxis verify           # every row verifies, or it screams
praxis report           # per-tier over/under allocation table
praxis calibrate        # complexity-score vs utilisation curve
```

See [`docs/receipts.md`](../docs/receipts.md) for the full verification
layer story.

## License

MIT.
