# Praxis × LiteLLM callback

A ~200-line Python callback that turns LiteLLM into a Praxis-aware gateway:
each request is scored, the correct reasoning-budget field is injected for
the target model family, and OpenInference-compatible telemetry is emitted
on response.

## Why this exists

LiteLLM (44.9k★ as of April 2026) is the hub every LLM observability tool
already plugs into — Langfuse, Phoenix, Helicone, OpenLLMetry, Lunary all
ship LiteLLM integrations. A single Praxis callback therefore lights up all
of them transitively.

## Quick start

```bash
pip install litellm
cp praxis_litellm.py /path/to/your/project/
```

```python
import litellm
from praxis_litellm import PraxisCallback

litellm.callbacks = [PraxisCallback()]

# All of these are now auto-budgeted by Praxis:
litellm.completion(model="claude-opus-4-7",
                   messages=[{"role": "user", "content": "Design a cache"}])
litellm.completion(model="o3-mini",
                   messages=[{"role": "user", "content": "Prove P≠NP"}])
litellm.completion(model="claude-opus-4-5",
                   messages=[{"role": "user", "content": "Fix the login bug"}])
```

What the callback does:

| Target model                   | Injected field                                            |
|--------------------------------|-----------------------------------------------------------|
| Claude Opus 4.7 / Mythos       | `thinking={"type":"adaptive"}` + `output_config.effort`   |
| Claude Opus 4.6 / Sonnet 4.6   | same + `output_config.effort` (no legacy `budget_tokens`) |
| Claude Opus 4.5 and earlier    | `thinking={"type":"enabled","budget_tokens":N}`           |
| OpenAI o-series / gpt-5-reason | `reasoning_effort={"low"\|"medium"\|"high"}`              |

## Telemetry

If an OpenTelemetry tracer is passed in, the callback emits the following
span attributes on every successful response:

```
praxis.complexity_score      7
praxis.tier_chosen           "heavy"
praxis.budget_requested      16384
praxis.effort_chosen         "high"
praxis.model_family          "adaptive_only"
praxis.reasoning_tokens_used 11200
praxis.budget_utilization    0.684
praxis.over_allocated        0
```

These live next to the OpenInference standard attributes
(`llm.token_count.completion_details.reasoning`, etc.) so dashboards in
Phoenix / Langfuse / any OTel collector render them automatically.

```python
from opentelemetry import trace
PraxisCallback(tracer=trace.get_tracer("praxis"))
```

## Honouring explicit user settings

The callback uses `dict.setdefault`, so any `thinking=`, `output_config=`,
or `reasoning_effort=` the caller passes by hand wins. Praxis only fills
in blanks.

## Testing

See `tests/test_praxis_litellm.py` (Python) in the same directory.
