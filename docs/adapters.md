# Adapters

Praxis is a **policy**, not a framework. The policy runs in 4 places today,
each wired via a ~100-line adapter:

| Surface | Module | Entry point | Install |
|---|---|---|---|
| Claude Code hook | `hooks/praxis-allocator.py` + `praxis-outcome.py` | `UserPromptSubmit` / `Stop` | already in-repo |
| LangChain / LangChain.js | `praxis.adapters.langchain` | `PraxisBudget` Runnable | `pip install 'praxis[langchain]'` |
| OpenAI Agents SDK | `praxis.adapters.openai_agents` | `PraxisRunHooks` | `pip install 'praxis[openai-agents]'` |
| LangGraph | `praxis.adapters.langgraph` | `with_praxis()` helper | `pip install 'praxis[langchain]'` |

Every adapter does exactly the same five steps:

1. Read the latest user prompt from whatever shape the framework gave us.
2. Call `praxis.allocate_for_model(prompt, model)` — scoring, tier,
   effort, and `thinking_config` in one shot.
3. Emit a signed `alloc` receipt to `allocation-log.jsonl`.
4. Mutate the outgoing request with the right vendor kwargs.
5. On the response, emit a paired `outcome` receipt to `outcome-log.jsonl`.

Because the *decision* is identical across adapters, `praxis verify` and
`praxis report` work uniformly against any mixed-framework ledger.

---

## LangChain

```python
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from praxis.adapters.langchain import PraxisBudget

base = ChatAnthropic(model="claude-opus-4-7", max_tokens=4096)
llm  = PraxisBudget(base, session_id="my-session")

reply = llm.invoke([HumanMessage("Design a distributed pipeline")])
```

`PraxisBudget` is a `Runnable`, so it composes with every LCEL primitive:
`RunnableSequence`, `with_fallbacks`, `with_retry`, pipes. It detects the
provider (`anthropic` / `openai` / `google`) from the wrapped model's class
name and emits the right kwargs per provider:

| Provider | Bound kwargs |
|---|---|
| Anthropic (Opus 4.7+) | `thinking={"type":"adaptive"}`, `output_config={"effort":...}` |
| Anthropic (Opus 4.6 / Sonnet 4.6) | same + `legacy_budget_tokens` for safety |
| Anthropic (Opus 4.5−, Haiku) | `thinking={"type":"enabled","budget_tokens":N}` |
| OpenAI (GPT-5.x) | `reasoning_effort="low\|medium\|high"` (xhigh/max collapse to high) |
| Google (Gemini 2.5/3) | `thinking_budget=N` |

## OpenAI Agents SDK

```python
from agents import Agent, Runner
from praxis.adapters.openai_agents import PraxisRunHooks

agent = Agent(name="Coder", model="gpt-5.3-codex")
hooks = PraxisRunHooks(session_id="my-session")

result = await Runner.run(agent, "Design a CRDT editor", hooks=hooks)
```

`PraxisRunHooks` patches `context.model_settings` via `ModelSettings.resolve()`
in `on_turn_start`, then pairs the outcome receipt in `on_turn_end`. The
SDK's multi-turn loop works unchanged; Praxis adjusts effort **per turn**
based on the user message that turn is responding to.

## LangGraph

```python
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_agent
from praxis.adapters.langgraph import with_praxis

llm = with_praxis(ChatAnthropic(model="claude-opus-4-7"), session_id="sess-1")
agent = create_agent(llm, tools=[...])
```

The LangGraph adapter is a trivial re-export of `PraxisBudget` — LangChain
Runnables *are* LangGraph nodes. Tool calling, handoffs, and checkpointing
all work unchanged.

---

## Writing a new adapter

Copy `praxis/adapters/langchain.py` as a template. The contract:

```python
from praxis.allocation import allocate_for_model
from praxis.adapters._outcome import emit_outcome

# In your framework's "before model call" hook:
alloc = allocate_for_model(prompt, model, session={"session_id": sid})
framework.bind(**translate_to_framework(alloc.thinking_config, alloc.effort))

# In your framework's "after model call" hook:
emit_outcome(alloc.session_id, alloc.turn_id,
             usage_source=response, stop_reason=..., tool_calls=...)
```

The only per-framework work is:
1. Where do I read the current prompt?
2. How do I set thinking kwargs per call?
3. How do I read usage from the response?

If those three points are all `None` away, ship the adapter.

---

## What the adapters do NOT do

- **Tool-call introspection.** We don't re-score mid-loop when the model
  decides to call a tool. The budget is set per *user turn*, not per tool
  call. Agent frameworks handle the loop; we handle the budget.
- **Streaming mutation.** Praxis can't change the effort level mid-stream.
  Effort is locked at request time.
- **Context compaction.** That's MAF's `context_window_size` territory, not
  ours. Composes cleanly though — compact first, then Praxis.
