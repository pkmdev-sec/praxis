# Competitive Landscape: Reasoning-Budget Allocation

**Question**: does any mainstream agent framework auto-map prompt complexity → tiered extended-thinking budget?

**Answer**: no. Fourteen projects surveyed; thirteen are `adjacent` (expose the *mechanism* — `thinking`, `reasoning_effort`, `thinking_budget` as static kwargs on the model client — but ship no *policy* that decides the budget from the prompt), one is `no` (Swarm — no reasoning surface at all). Praxis occupies the empty policy quadrant. GitHub-wide searches for `"thinking budget" agent`, `"extended_thinking" complexity`, and `"thinking budget" claude code hook` all return **0 repositories** (2026-04-28). The single architecturally closest project — `Yarin-Shitrit/ccpilot`, a `UserPromptSubmit` hook that classifies prompts and injects skill/subagent suggestions — routes to a completely different target surface (skills, not thinking tokens).

## Praxis tiers (the reference policy)

Praxis emits *both* output shapes that Anthropic currently supports and picks the right one per target model (`lib/effort-mapper.mjs::classifyModelFamily`):

| Complexity | Tier   | `budget_tokens` (legacy / Opus ≤4.5, Haiku, Sonnet 3.7) | `effort` (Opus 4.6+ / Sonnet 4.6 / Mythos) |
|-----------:|--------|--------------------------------------------------------:|:-------------------------------------------|
| 1–2        | None   |                                                       0 | *(thinking skipped — no block)*            |
| 3–4        | Light  |                                                   2,048 | `low`                                       |
| 5–6        | Medium |                                                   8,192 | `medium`                                    |
| 7–8        | Heavy  |                                                  16,384 | `high`                                      |
| 9–10       | Max    |                                                  32,768 | `xhigh` (score 9) / `max` (score 10)        |

Model-family routing is enforced in code: `adaptive_only` (Opus 4.7, Mythos) → emits `{type:"adaptive", effort}` only; `adaptive_preferred` (Opus 4.6, Sonnet 4.6) → emits both and prefers `effort`; `manual` (Opus ≤4.5, Haiku, Sonnet 3.7) → emits `{type:"enabled", budget_tokens:N}`. See `docs/core-concepts/budget-allocation.md`, `docs/core-concepts/complexity-scoring.md`, and `lib/effort-mapper.mjs:1`.

## Summary matrix

| Framework                   | Verdict    | Mechanism (what's there)                                   | Policy (what's missing)                  | Stars | Last release |
|-----------------------------|------------|------------------------------------------------------------|------------------------------------------|------:|--------------|
| langchain-ai/langchain      | `adjacent` | `ChatAnthropic.thinking={budget_tokens}`, `reasoning_effort`, `task_budget`, beta headers | No prompt classifier; user picks at model construction | ~135k | active (daily) |
| microsoft/autogen           | `adjacent` | Static `thinking` / `reasoning_effort` on model client     | No complexity router, no GroupChat budget allocator | 57.5k | `python-v0.7.5` (Sep 30, 2025) — **maintenance mode** |
| crewAIInc/crewAI            | `adjacent` | LLM wrapper accepts `thinking` / `reasoning_effort` kwargs; `max_iter`/`max_rpm`/`max_execution_time` are loop caps | No prompt introspection; YAML agents are static | 50.1k | `1.14.3` (Apr 24, 2026) |
| run-llama/llama_index       | `adjacent` | Typed `Anthropic(thinking_dict={...})` + auto-`temperature=1`; via `_get_all_kwargs()` | No classifier; init-time only; `max_iterations` is ReAct cap | 49k   | `v0.14.21` (Apr 21, 2026) |
| agno-agi/agno               | `adjacent` | `claude.py`: `thinking: Optional[Dict[str, Any]] = None` dataclass field passed verbatim; `NON_THINKING_MODELS` is capability gate only | No prompt inspection; "Reasoning Agents" is CoT prompting, not budget allocation | 39.7k | `v2.6.2` (Apr 27, 2026) |
| langchain-ai/langgraph      | `adjacent` | Inherits `ChatAnthropic.thinking=`, `ChatOpenAI.reasoning_effort=`, `ChatVertexAI.thinking_budget=` | No node- or graph-level budget allocator | 30.6k | `langgraph==1.1.10` (Apr 27, 2026) |
| openai/openai-agents-python | `adjacent` | `ModelSettings.reasoning`, `extra_args`, per-run `resolve()` override | No classifier driving the override | 25.4k | `v0.14.6` (Apr 25, 2026) |
| deepset-ai/haystack         | `adjacent` | `generation_kwargs={"thinking":{...}}` dict stuffed into provider SDK; `Agent(max_agent_steps=100)` is loop cap | Weakest typing — no named fields; static DAGs | 25k   | `v2.28.0` (Apr 20, 2026) |
| mastra-ai/mastra (TS)       | `adjacent` | Via Vercel AI SDK: `providerOptions.anthropic.thinking`; workflow `.then()`/`.branch()` are step caps | No classifier; only TS entry — Praxis hook needs TS port | 23.4k | active (Apr 24, 2026) |
| openai/swarm                | **`no`**   | Agent fields: `name/model/instructions/functions/tool_choice` — nothing else; Chat-Completions only | No reasoning surface at all | 21.4k | **29 commits, 0 releases — frozen; superseded by Agents SDK** |
| pydantic/pydantic-ai        | `adjacent` | `capabilities/thinking.py`: `Thinking(effort: ThinkingLevel)` with 5 levels — cleanest cross-provider normalization | Levels are developer-set; no prompt inspection | 16.7k | `v1.87.0` (Apr 25, 2026) |
| microsoft/agent-framework   | `adjacent` | Per-client reasoning kwargs across Anthropic/OpenAI/Gemini/Ollama | No policy; active adaptive-context work suggests slot is open | 9.9k  | `python-1.2.0` (Apr 24, 2026) |
| stanfordnlp/dspy            | `adjacent` | Everything via LiteLLM; `_convert_chat_request_to_responses_request` maps `reasoning_effort` → `reasoning={"effort":…, "summary":"auto"}` for OpenAI Responses; reasoning-model regex gates `temperature=1.0`/`max_tokens≥16000` | No classifier; orthogonal paradigm is *prompt optimization* (GEPA/MIPRO) — optimizes instructions, not budgets | 34k   | active (daily) |
| huggingface/smolagents      | `adjacent` | Reasoning params via `**kwargs` → `_prepare_completion_kwargs`; `max_tokens`/`max_new_tokens` are decode-time caps; `LiteLLMRouterModel` load-balances *between models* (RouteLLM axis) | Kwargs-only — weakest typing after Haystack; no named thinking fields on any `Model` subclass | ~14k  | active |


## Per-framework detail

### langchain-ai/langchain — `adjacent`

- **Behavior**: LLM application framework with 100+ integrations; `langchain-anthropic.ChatAnthropic` exposes `thinking={"type":"enabled","budget_tokens":N}` plus newer `thinking_budget=` / `task_budget=` fields, all forwarded verbatim to the Anthropic SDK.
- **Budget allocation**: `adjacent`. Richest plumbing of the set (`thinking`, `reasoning_effort`, `task_budget`, beta headers), zero routing logic. Values are locked at `ChatAnthropic(...)` construction or supplied per-call by the developer.
- **Gap vs Praxis**: No hook layer introspects the prompt. A Praxis-shape wrapper would need to sit as a `Runnable` that rewrites `thinking` on each invocation based on input.
- **Maturity**: ~135k ⭐, daily releases; ecosystem-central.
- **URL**: https://github.com/langchain-ai/langchain

### crewAIInc/crewAI — `adjacent`

- **Behavior**: Lean multi-agent framework (Crews + Flows) built from scratch, independent of LangChain. Agents configured via YAML (`role/goal/backstory/tools/memory/guardrails`); LLMs wrapped with `LLM(...)` accepting static `thinking` / `reasoning_effort` kwargs.
- **Budget allocation**: `adjacent`. Existing knobs (`max_iter`, `max_rpm`, `max_execution_time`) are loop/rate limits, **not** per-LLM thinking tokens. README's *Agent Fields* make no mention of thinking budget.
- **Gap vs Praxis**: No classifier, no tiers; YAML-defined agents can't introspect prompts. Praxis would need to sit ahead of the LLM wrapper.
- **Maturity**: 50.1k ⭐, 180 releases, `1.14.3` Apr 24, 2026; MIT; standalone (no LangChain dependency).
- **URL**: https://github.com/crewAIInc/crewAI

### run-llama/llama_index — `adjacent`

- **Behavior**: Data/agent framework for RAG and document agents. `llama-index-integrations/llms/llama-index-llms-anthropic/.../base.py` exposes typed `thinking_dict: Optional[Dict[str, Any]]` (README example: `{"type":"enabled","budget_tokens":16000}`), auto-forces `temperature=1` when thinking is enabled, and plumbs via `_get_all_kwargs()` to `messages.create(**all_kwargs)`.
- **Budget allocation**: `adjacent`. First-class typed field for `budget_tokens` — stricter than AutoGen/CrewAI — but purely user-configured at `Anthropic(...)` construction. No `reasoning_effort` first-class surface (passes via `additional_kwargs`). `max_iterations` in the workflow/agent layer is a ReAct loop cap.
- **Gap vs Praxis**: Same as LangChain — user picks a single `budget_tokens` value at instantiation. No auto-tier mapping.
- **Maturity**: 49k ⭐, 493 releases, `v0.14.21` Apr 21, 2026; recent PRs (#21423 Apr 20, #20852, #20355) are on thinking-*block handling*, not budget routing.
- **URL**: https://github.com/run-llama/llama_index

### agno-agi/agno — `adjacent`

- **Behavior**: Agent runtime (AgentOS + SDK) — serves agents as FastAPI services with sessions/tracing/RBAC. Wraps Claude Agent SDK, LangGraph, DSPy.
- **Budget allocation**: `adjacent`. Verified from `libs/agno/agno/models/anthropic/claude.py`: `thinking: Optional[Dict[str, Any]] = None` is a static `@dataclass` field; `_prepare_request_kwargs()` forwards it unchanged. `_validate_thinking_support()` only checks the `NON_THINKING_MODELS` set — capability gate, never inspects the prompt.
- **Gap vs Praxis**: "Reasoning Agents" branding in the docs is about chain-of-thought prompting, **not** dynamic budget allocation. Same init-time limitation as every other Python framework.
- **Maturity**: 39.7k ⭐, 185 releases, `v2.6.2` Apr 27, 2026 (yesterday); rebrand from Phidata.
- **URL**: https://github.com/agno-agi/agno

### deepset-ai/haystack — `adjacent`

- **Behavior**: RAG/pipeline framework; `haystack/components/agents/agent.py` implements a loop-based `Agent` component. Chat generators (`AnthropicChatGenerator`, `OpenAIChatGenerator`) accept arbitrary `generation_kwargs` passed straight to the provider SDK.
- **Budget allocation**: `adjacent` — weakest typing of any surveyed framework. Users write `generation_kwargs={"thinking":{"type":"enabled","budget_tokens":8000}}` at generator construction. `Agent(max_agent_steps=100)` is loop cap. PR #10378 (merged Jan 14, 2026) only *flattens* these kwargs; issue #8760 "Support for o1-like reasoning model (LRMs)" sits as P3.
- **Gap vs Praxis**: No named `thinking`/`effort` fields on generator dataclasses; pipelines are static DAGs with no prompt-introspection hook. Would require a custom `Component` wrapper.
- **Maturity**: 25k ⭐, 223 releases, `v2.28.0` Apr 20, 2026; Apache-2.0; deepset-backed (enterprise tier).
- **URL**: https://github.com/deepset-ai/haystack

### mastra-ai/mastra — `adjacent` (TypeScript)

- **Behavior**: TypeScript agent framework on top of the Vercel AI SDK — no first-party Anthropic client; reasoning-budget support is whatever `@ai-sdk/anthropic` offers, wired via `providerOptions: { anthropic: { thinking: {...} } }` on `Agent(model: …)` / `generate()` / `stream()`.
- **Budget allocation**: `adjacent` (passthrough). No Mastra-level typed field. Graph workflow engine (`.then()`/`.branch()`/`.parallel()`) has per-step/iter limits — not per-call thinking budgets.
- **Gap vs Praxis**: Only TypeScript entry in the survey — Praxis's Claude Code hook pattern would need a TS-side equivalent to integrate here.
- **Maturity**: 23.4k ⭐, 14,503 commits (highest in survey), 78 releases, active Apr 24, 2026; 99.4% TypeScript; first-class Next.js/React/Node.
- **URL**: https://github.com/mastra-ai/mastra

### openai/swarm — **`no`**

- **Behavior**: Stateless client-side multi-agent loop over Chat Completions. Agent fields: `name/model/instructions/functions/tool_choice`. `client.run()` args: `agent/messages/context_variables/max_turns/model_override/execute_tools/stream/debug`. That is the entire surface.
- **Budget allocation**: **`no`**. Predates o1/reasoning models; Chat-Completions only. Repo code search for `reasoning_effort` → 0 files. README: *"Swarm is entirely powered by the Chat Completions API and is hence stateless between calls."*
- **Gap vs Praxis**: Total. No reasoning surface exists; the successor (OpenAI Agents SDK, covered below) is the place to integrate.
- **Maturity**: 21.4k ⭐ / 2.3k forks; **29 commits total, 0 releases, 0 tags**. README banner: *"Swarm is now replaced by the **OpenAI Agents SDK** … We recommend migrating to the Agents SDK for all production use cases."* Frozen/educational.
- **URL**: https://github.com/openai/swarm

### pydantic/pydantic-ai — `adjacent` (closest structural match)

- **Behavior**: Type-safe agent framework from the Pydantic team with a composable "capabilities" system. `pydantic_ai_slim/pydantic_ai/capabilities/thinking.py` defines `Thinking(effort: ThinkingLevel = True)` with effort ∈ `{True, False, 'minimal', 'low', 'medium', 'high', 'xhigh'}`; it emits unified `ModelSettings(thinking=…)` and the provider layer translates to `anthropic_thinking` / `openai_reasoning_effort`.
- **Budget allocation**: `adjacent` — **the cleanest abstraction of all surveyed frameworks**. Still static: set at `Agent(..., capabilities=[Thinking(effort='high')])`. Per-call override via `model_settings=` on `run()` is developer-driven. Issues #5196 (merged Apr 24, 2026) and #5153 ("Claude 4.7 Opus adaptive thinking") show active plumbing work, not classifier work.
- **Gap vs Praxis**: Closest aesthetic match — named effort tiers map roughly to Praxis's ladder — but *who picks which level* is still the developer. The `capabilities/` directory already hosts `thread_executor`, `reinject_system_prompt`, `process_history`: the hook points exist and nobody has built a complexity-router on top. **Best upstream integration target.**
- **Maturity**: 16.7k ⭐, 239 releases, `v1.87.0` Apr 25, 2026; Pydantic-team-backed; fastest-growing of the set.
- **URL**: https://github.com/pydantic/pydantic-ai

### stanfordnlp/dspy — `adjacent`

- **Behavior**: Programmatic prompt/LM framework. `dspy/clients/lm.py` routes every call through LiteLLM. Reasoning handling has two pieces: (a) a regex capability gate `r"^(?:o[1345](?:-(?:mini|nano|pro))?(?:-\d{4}-\d{2}-\d{2})?|gpt-5(?!-chat)(?:-.*)?)$"` that forces `temperature=1.0` and `max_tokens ≥ 16000` for OpenAI reasoning models; (b) `_convert_chat_request_to_responses_request` which translates `reasoning_effort="high"` into `reasoning={"effort":"high","summary":"auto"}` for the OpenAI Responses API.
- **Budget allocation**: `adjacent`. Effort/reasoning is pure passthrough; no per-call adjustment from prompt content. DSPy's actual differentiator is orthogonal: the `GEPA`, `MIPRO`, and `BootstrapFewShot` *optimizers* compile the prompt/program itself — they tune instructions and demonstrations, not thinking budget.
- **Gap vs Praxis**: Different paradigm entirely. Praxis = "compile nothing, score the input, pick the budget." DSPy = "compile the program, hope the model does the rest." The two are complementary, not competing — a Praxis-style budget selector could drop in as a `dspy.LM` subclass that inspects `messages` before dispatching.
- **Maturity**: ~34k ⭐, daily commits.
- **URL**: https://github.com/stanfordnlp/dspy

### huggingface/smolagents — `adjacent`

- **Behavior**: Minimal agent framework (CodeAgent/ToolCallingAgent) from Hugging Face. `src/smolagents/models.py` defines a `Model` base class whose `_prepare_completion_kwargs` merges `self.kwargs` (init-time) with per-call `**kwargs` and passes everything verbatim to the backend (`LiteLLMModel`, `InferenceClientModel`, `OpenAIModel`, `AmazonBedrockModel`, …). No `thinking` or `reasoning_effort` field on any `Model` subclass — everything is opaque `**kwargs`. Notable: `LiteLLMRouterModel` load-balances *between* models via LiteLLM's `Router` (`routing_strategy="simple-shuffle"`), which is the model-tier routing axis (RouteLLM-adjacent), not thinking-budget routing.
- **Budget allocation**: `adjacent` — the weakest typing in the Python survey after Haystack. The only first-class cap is `max_tokens`/`max_new_tokens`, which is decode-time, not reasoning budget.
- **Gap vs Praxis**: No classifier, no tiers. Smolagents is philosophically "lean" — it won't add policy knobs, so a Praxis integration would have to be a thin `Model` wrapper that injects `thinking={...}` into `kwargs` based on the `messages` payload.
- **Maturity**: ~14k ⭐, active; HF-backed; Apache-2.0.
- **URL**: https://github.com/huggingface/smolagents

### microsoft/autogen — `adjacent`

- **Behavior**: Multi-agent orchestration (AgentChat, GroupChat, SelectorGroupChat); in community maintenance mode. `autogen_ext/models/anthropic/_anthropic_client.py` includes `"thinking"` in `anthropic_message_params`; `_get_thinking_config()` just reads `extra_create_args.get("thinking")` → `self._create_args.get("thinking")` and forwards verbatim.
- **Budget allocation**: `adjacent`. PR #7002 (merged Sep 16, 2025) added Anthropic `thinking` passthrough. PR #7054 (merged Sep 30, 2025) added `reasoning_effort` for GPT-5. `SelectorGroupChat` has `max_turns` / `max_selector_attempts` but zero token/cost fields.
- **Gap vs Praxis**: developer must hard-code `AnthropicChatCompletionClient(model=..., thinking={...})` per instance; no orchestrator-level adaptive layer.
- **Maturity**: 57.5k ⭐, 8.7k forks, 3,782 commits; latest `python-v0.7.5` Sep 30, 2025. README: *"AutoGen is now in maintenance mode… New users should start with Microsoft Agent Framework."*
- **URL**: https://github.com/microsoft/autogen

### microsoft/agent-framework — `adjacent`

- **Behavior**: AutoGen's successor; Python + .NET; graph-based workflows, DevUI, A2A/MCP, clients for `anthropic`/`claude`/`openai`/`bedrock`/`gemini`/`ollama`/`foundry`.
- **Budget allocation**: `adjacent`. Issue signals (#5361 Ollama thinking-mode, #5381 llama.cpp reasoning content, #5327 `delta.reasoning_content`, #5340 AG-UI reasoning) are all plumbing/surfacing — no complexity router. #5304 ".NET: Add context window size compaction strategy for harness" (merged Apr 16, 2026) shows the team is shipping adaptive *resource* policies, so a reasoning-budget policy is a natural next slot.
- **Gap vs Praxis**: same as AutoGen, on a live, high-velocity surface — Praxis lands the gap before MAF fills it.
- **Maturity**: 9.9k ⭐, 1.6k forks, 1,957 commits; `python-1.2.0` Apr 24, 2026; 606 issues / 190 PRs active.
- **URL**: https://github.com/microsoft/agent-framework

### langchain-ai/langgraph — `adjacent`

- **Behavior**: Low-level graph orchestration (StateGraph, create_agent, checkpointing, HITL). Delegates all LLM calls to `langchain-core` chat models.
- **Budget allocation**: `adjacent`. LangChain chat models forward Anthropic `thinking={"type":"enabled","budget_tokens":N}`, OpenAI `reasoning_effort`, Gemini `thinking_budget` verbatim (issue #4175 "Anthropic Thinking 400 error"; langchain #31767 "thinking_budget not working for chains"; #34933 "Handling 'reasoning' blocks when switching between providers"; prebuilt fixes #7386/#7388 "strip extended thinking before `with_structured_output`"). LangGraph's own `budget tokens` search returns only ReAct/recursion-limit issues (#6617, #6731, #7138).
- **Gap vs Praxis**: each node hard-codes a `ChatAnthropic(..., thinking={...})` binding; varying the budget per invocation requires manually swapping the model. Praxis-equivalent plugin for `create_agent` / node pre-hooks is an obvious integration surface.
- **Maturity**: 30.6k ⭐, 5.2k forks, 6,771 commits; `langgraph==1.1.10` Apr 27, 2026; v1 roadmap issue #4973 open; sibling `LangGraph.js`; commercial LangChain Inc + LangSmith backing.
- **URL**: https://github.com/langchain-ai/langgraph

### openai/openai-agents-python — `adjacent`

- **Behavior**: Official OpenAI SDK for multi-agent workflows (Agents, Handoffs, Guardrails, Sessions, Sandbox Agents, Tracing); provider-agnostic via `LitellmModel`.
- **Budget allocation**: `adjacent`. `src/agents/model_settings.py` defines `ModelSettings` with static `reasoning: Reasoning | None`, `max_tokens`, `verbosity`, `extra_args`, and a `resolve(override)` that overlays a per-run override — a per-call override *surface*, but no policy. Anthropic thinking support: PRs #1744 (merged Sep 16, 2025), #1784, #1798. LiteLLM `reasoning_effort` portability: #2782 (merged Mar 26, 2026).
- **Gap vs Praxis**: SDK ships the mechanism (`resolve()` + per-turn hooks; see #2911 `on_turn_start` / `on_turn_end` with `TurnControl`, and open #2970 pre-execution validation) but not the policy. Praxis is the classifier that *drives* `resolve()`.
- **Maturity**: 25.4k ⭐, 3.9k forks, 1,386 commits; `v0.14.6` Apr 25, 2026; 88 releases; tight official OpenAI maintenance; Sandbox Agents in 0.14.0.
- **URL**: https://github.com/openai/openai-agents-python

## Thesis

Every mainstream agent framework treats extended-thinking / reasoning-effort as a **configuration knob** exposed to the developer. None treats it as a **decision** to be made per-prompt by a classifier. Praxis is a Claude Code hook that fills exactly that gap, and the same policy would drop cleanly into any of the four frameworks above — `ModelSettings.resolve()` in OpenAI Agents SDK, a node pre-hook in LangGraph, `extra_create_args={"thinking": ...}` in AutoGen/MAF — because they all already accept a per-call override dict. The gap is policy, not plumbing.

## Prior art on prompt-complexity scoring

Praxis's scorer (`lib/complexity-scorer.mjs`, 1–10 rule-based) is not the first prompt-complexity scorer. Two pieces of prior art matter; neither is a head-on competitor to the Praxis *policy*, but both must be acknowledged.

| Artifact | Shape | Stars / Downloads | Maintained? | Relation to Praxis |
|---|---|---|---|---|
| [`nvidia/prompt-task-and-complexity-classifier`](https://huggingface.co/nvidia/prompt-task-and-complexity-classifier) (NemoCurator) | DeBERTa-v3 multi-head classifier: 11 task types + 6 complexity dims (Creativity, Reasoning, Constraint, Domain, Contextual, Few-Shots), overall = `0.35·Creativity + 0.25·Reasoning + 0.15·Constraint + 0.15·Domain + 0.05·Contextual + 0.05·FewShots`. 98%+ top-1 on 4,024 human-labeled prompts. | 28,279 HF downloads, 80 likes | ✅ last modified 2025-09-22 | Direct substitute **for the scorer only**. Higher accuracy but requires GPU (CUDA 12, A10G-class), 512-token cap, NVIDIA Open Model License. Natural `scorer: "nemocurator"` adapter for a future Praxis v2. |
| [`lm-sys/RouteLLM`](https://github.com/lm-sys/RouteLLM) | Framework for training/serving routers (MF, BERT, causal LLM, similarity-weighted) on Chatbot Arena preference data. Drop-in OpenAI client that routes across *two* models. | 4,832 ★, 374 forks | ❌ last commit 2024-08-09 (~20 months stale) | Citation-canonical but architecturally orthogonal: RouteLLM picks *which model* to call; Praxis picks *how much thinking* a single model gets. The policy surface doesn't overlap. |
| [`simplescaling/s1`](https://github.com/simplescaling/s1) (Muennighoff et al., Jan 2025, [arXiv:2501.19393](https://arxiv.org/abs/2501.19393)) | **Budget forcing**: generation-time control that either (a) forcefully terminates the model's thinking trace, or (b) suppresses the end-of-thinking token and appends "Wait" to *extend* reasoning. Applied to `s1-32B` (Qwen2.5-32B SFT'd on 1K curated traces). | 6.6k ★ | ✅ active 2025 (open weights + data + code, Apache-2.0) | Genuine academic antecedent for *test-time compute control*, but operates at a different layer: S1 manipulates **decoding** on an open-weights model after SFT; Praxis picks an **API parameter** (`effort` / `budget_tokens`) before a closed-weights API call. The S1 paper proves dynamic compute allocation helps (MATH/AIME24 +27%); Praxis is a productized, closed-weights analog of the same intuition, minus the SFT step. |

**Adjacent but not prior art on scoring (model-tier routing axis)**: gateway/router products (`Portkey-AI/gateway` 11.5k★, `katanemo/plano` 6.4k★, `vllm-project/semantic-router` 3.9k★, `coaidev/coai` 9.1k★, `Not-Diamond/notdiamond-python` 90★). All ship routing with embedded complexity heuristics but expose no standalone scorer and no extended-thinking-budget policy.

**Implication.** The scoring *function* is table stakes — NemoCurator already does it better than a regex tiering ever will, and S1 has proven the *"dynamic compute → better reasoning"* intuition at the academic level. Praxis's defensibility is the **policy layer** above the score: the 5-tier budget map, the model-family-aware emission (`lib/effort-mapper.mjs:classifyModelFamily`), the Claude Code hook integration, and the empty policy quadrant across AutoGen/MAF/LangGraph/OpenAI Agents documented below. An optional NemoCurator adapter in a future minor release would neutralize the *"just use NVIDIA's classifier"* objection without changing the Praxis thesis.

## Broad GitHub search for prior art (2026-04-28)

All queries executed via obscura `browser_fetch` against `https://github.com/search?q=…&type=repositories`:

| Query | Repository results |
|---|---|
| `"thinking budget" agent` | **0** |
| `"extended_thinking" complexity` | **0** |
| `claude code hook thinking complexity` | **0** |
| `"reasoning_effort" router claude` | 1 (OCaml LLM client — generic, not a router) |
| `prompt complexity router budget` | 3: `shrivastava03/llm_router_agent` (5⭐), `Saimoguloju/lc-shift` (0⭐), `Sapience-AI/openclaw-middleware-suite` (0⭐) — **all three route between model *tiers*, not between thinking *budgets*** (different axis) |

The complexity→extended-thinking-budget mapping Praxis implements is unclaimed on GitHub.

## Claude Code hook ecosystem (closest architectural space)

The `UserPromptSubmit` hook pattern Praxis uses is *not* rare — searching GitHub for `claude-code hook` returns **~3.4k repositories** (top hits: `disler/claude-code-hooks-mastery` 3.6k⭐, `hesreallyhim/awesome-claude-code` 41.5k⭐, `ChrisWiles/claude-code-showcase` 5.9k⭐, `CloudAI-X/claude-workflow-v2` 1.3k⭐). But scanning the top-10 by stars for every hook, none addresses thinking-budget allocation; they cover observability, notifications, memory, voice, slash-commands, security, permissions, session capture, and project scaffolding. The specific combination `"thinking budget" claude code hook` returns **0 repositories**.

The single architecturally-closest project is **`Yarin-Shitrit/ccpilot`** (1⭐, 3 commits, Python, Apr 2026):

- **Behavior**: Installs a `UserPromptSubmit` hook that classifies each prompt (intent + complexity + confidence) with a stdlib heuristic, optionally escalates low-confidence prompts to Haiku, then injects a routing block so Claude "automatically dispatches the right skills and subagents." Optional Raft-lite swarm consensus for high-stakes runs.
- **Overlap with Praxis**: **Architecture is nearly identical** — both are Python hooks on `UserPromptSubmit` that score prompts with a local classifier and inject a block. Config path `~/.claude/ccpilot/config.toml` vs Praxis's own config; both default-off paths exist.
- **Divergence from Praxis**: Target surface is completely different. ccpilot routes to skills + subagents (a *what to call* policy); Praxis routes to extended-thinking budget (a *how hard to think* policy). The two are orthogonal and composable — ccpilot could dispatch a subagent that Praxis then budgets.
- **Verdict**: ccpilot validates the "UserPromptSubmit + classifier" *pattern* but leaves the thinking-budget *application* entirely open. It is the strongest confirmation yet that the empty policy quadrant is genuine: someone built the pattern, chose a different target.

## Thesis risk: Anthropic's server-side adaptive thinking

The strongest argument *against* Praxis is that Anthropic itself now ships server-side adaptive reasoning, directly on the model. A thorough review of Anthropic's docs (2026-04-28) surfaced three relevant server-side mechanisms:

### 1. Adaptive thinking — `thinking: {type: "adaptive"}`

Source: [`docs.anthropic.com/en/docs/build-with-claude/adaptive-thinking`](https://docs.anthropic.com/en/docs/build-with-claude/adaptive-thinking).

- **What it does**: *"Claude evaluates the complexity of each request and determines whether and how much to use extended thinking."* Default mode on Claude Mythos Preview; the only supported mode on Claude Opus 4.7 (manual `budget_tokens` returns 400).
- **What this breaks for naive competitors**: any framework that hard-codes `thinking: {type:"enabled", budget_tokens:N}` (AutoGen, LlamaIndex `thinking_dict`, Agno, Haystack `generation_kwargs`) is on a deprecation path on Opus 4.6/Sonnet 4.6 and is **already incompatible** with Opus 4.7.
- **What this does *not* break for Praxis**: Praxis already emits both shapes per model family. `lib/effort-mapper.mjs::EFFORT_TIERS` maps complexity → `low/medium/high/xhigh/max`; `classifyModelFamily` (regex on model name) picks `adaptive_only` vs `adaptive_preferred` vs `manual`; `buildThinkingConfig(complexity, family)` returns `{thinking:{type:"adaptive"}, output_config:{effort}}` for adaptive-only models, both shapes for adaptive-preferred, and `{thinking:{type:"enabled", budget_tokens:N}}` for manual. The Python hook at `hooks/praxis-allocator.py::build_thinking_config` mirrors this logic exactly (lines 182, 192, 212–224).

### 2. Effort parameter — `output_config: {effort}`

Source: [`docs.anthropic.com/en/docs/build-with-claude/effort`](https://docs.anthropic.com/en/docs/build-with-claude/effort).

- **What it does**: A five-level enum (`low`/`medium`/`high`/`xhigh`/`max`) that, per Anthropic's own docs, *"affects all tokens in the response, including text responses, tool calls, and extended thinking."*
- **Is this a classifier?** No. Anthropic explicitly tells developers *"Consider dynamic effort: Adjust effort based on task complexity"* — but ships **no classifier** to do so. The developer is still responsible for picking the tier per prompt.
- **Where Praxis fits**: Praxis *is* the missing classifier. `lib/effort-mapper.mjs::EFFORT_TIERS` maps the 1–10 complexity score to exactly this enum (`{3,4}→low, {5,6}→medium, {7,8}→high, 9→xhigh, 10→max`, and null/skip below). Without Praxis (or an equivalent), the developer either sets a single effort level at agent construction (Pydantic AI pattern) or manually picks per call (`ModelSettings.resolve()` in Agents SDK).

### 3. Task budgets (beta) — `output_config: {task_budget: {type:"tokens", total}}`

Source: [`docs.anthropic.com/en/docs/build-with-claude/task-budgets`](https://docs.anthropic.com/en/docs/build-with-claude/task-budgets). Beta header `task-budgets-2026-03-13`, public beta on Opus 4.7 only.

- **What it does**: Caps the *full agentic loop* (thinking + tool calls + tool results + output) with a soft, advisory countdown the model sees and paces against.
- **Relationship to Praxis**: Orthogonal axis. Anthropic's docs explicitly state: *"effort controls how thoroughly Claude reasons about each step, while task budgets cap the total work Claude can do across an agentic loop."* Praxis selects the *effort tier* (per-prompt); task budgets cap the *loop total* (cross-turn). They compose cleanly — a future Praxis feature could also set `task_budget.total` as a function of complexity.
- **Critical constraint**: *"Task budgets are **not** supported on Claude Code or Cowork surfaces at launch. Use task budgets directly via the Messages API on Claude Opus 4.7."* Praxis's Claude Code hook can't use task budgets today; the SDK integration could.

### Net assessment

Anthropic shipped the *mechanism* (adaptive thinking, effort enum, task budgets). They did not ship the *classifier*. The closest they come is a line in the effort docs' "Best practices" — *"Consider dynamic effort: Adjust effort based on task complexity"* — which names the gap rather than filling it.

The empty-quadrant thesis survives with one caveat: **the thesis has shifted from `budget_tokens` to `effort`**. On current and future Anthropic models, "picking the thinking budget" increasingly means "picking the effort tier." Praxis has already made that transition (`lib/effort-mapper.mjs`, `hooks/praxis-allocator.py::build_thinking_config`), so it lands on the modern surface rather than the deprecated one. Frameworks that only plumbed `budget_tokens` will need to migrate; Praxis already has.

## Evidence provenance (pass 1 — agent frameworks)

Investigation performed via Obscura MCP browser tools on 2026-04-28. See session transcript for raw `browser_fetch` output including `_anthropic_client.py`, `_selector_group_chat.py`, `model_settings.py`, and issue-search result pages.

---

## Observability & Gateway quadrant (added 2026-04-28)

Second-pass survey across 11 LLM observability / gateway projects via Obscura
browser MCP. Same question, different axis: can any of them *automatically
adjust reasoning budget* for future calls based on latency/cost/quality traces?

**Answer**: no. All 11 are either `read-only observability` (emit telemetry,
never mutate request shape) or `static routing` (expose conditional routing /
fallback rules that a human hand-authors). Closed-loop budget selection is an
empty quadrant, orthogonal to the agent-framework quadrant above. Praxis sits
in both empty quadrants at once.

### Read-only observability (6 projects)

| Project        | Stars | Last release | Budget loop | Claude thinking integration |
|----------------|------:|--------------|-------------|-----------------------------|
| Langfuse       | 26.2k | v3.171.0 (Apr 27 2026) | `read_only` | OTel via LiteLLM / OpenLLMetry span processor |
| Phoenix (Arize)|  9.5k | arize-phoenix v14.15.0 (Apr 26 2026) | `read_only` | OpenInference `claude-agent-sdk` instrumentor |
| OpenLLMetry    |  7.0k | 0.60.0 (Apr 19 2026) | `read_only` | OTel instrumentation lib (Anthropic included) |
| Helicone (obs) |  5.6k | v2025.08.21-1 (Aug 2025) | `read_only` | Async logging via OpenLLMetry |
| LangSmith      | closed| GA | `read_only` | LangChain chat-model forwarding only |
| Lunary         | — (main repo 404) | — | `read_only` | Org appears to be shrinking — `lunary-py` archived, main repo gone |

All six *record* `llm.token_count.completion_details.reasoning` and similar
attributes (per the OpenInference spec) but none *decide* budgets from them.

### Static routing / gateway (4 projects)

| Project    | Stars | Last release | Budget loop | Note |
|------------|------:|--------------|-------------|------|
| LiteLLM    | **44.9k** | v1.83.14.rc.1 (Apr 27 2026) | `adjacent` — pass-through | Biggest by far; every observability tool plugs in via a callback |
| Portkey    | 11.5k | v1.15.2 (Jan 12 2026) | `adjacent` — conditional routing on `params.max_tokens` | Routes *models*; no budget-per-prompt policy |
| Helicone AI Gateway | (within 5.6k above) | same | `adjacent` — fallbacks + LB | No quality feedback loop |
| Pezzo      |  3.2k | v0.9.2 (May 15 2024) | `dormant` | Effectively abandoned |

### Quality-aware model routers (2 projects — closest in spirit)

| Project                         | Stars | Status | Knob it controls |
|--------------------------------|------:|--------|------------------|
| `lm-sys/RouteLLM`              |  4.8k | research (no releases) | Binary strong/weak **model** swap, calibrated once on Chatbot Arena preferences |
| `Not-Diamond/notdiamond-python`|    90 | **archived Dec 11 2025** | Meta-model picks an LLM per prompt |

RouteLLM is the closest spiritual sibling but (a) picks models not budgets,
(b) calibrates once against a public dataset, not online against your traces,
(c) has no Claude extended-thinking awareness.

### Anthropic native baseline (existential threat surface)

During this pass we verified that **Anthropic themselves now ship most of
what a naive `budget_tokens` allocator would do**:

- **Adaptive Thinking** (`thinking: {type: "adaptive"}`): the model picks its
  own thinking depth per request. **Required** on Claude Opus 4.7 (manual
  `budget_tokens` returns 400); **recommended** on Opus 4.6 / Sonnet 4.6
  (manual deprecated).
- **`effort` enum** (`output_config.effort = low|medium|high|xhigh|max`):
  coarse soft hint, replaces the integer budget as the recommended knob.
- **Task Budgets (beta)** (`output_config.task_budget.total`, min 20,000
  tokens, beta header `task-budgets-2026-03-13`): a server-tracked countdown
  that spans the full agentic loop. Anthropic's own docs punt sizing to the
  user: *"Start with the p99 of your per-task token spend … test up or down."*

These ship the *mechanism*; none of them ships a *policy* for which `effort`
tier to choose, or what `task_budget.total` to set. That's still Praxis.

### Cross-provider knob landscape (April 2026)

The whole industry converged on an effort/level enum + a legacy integer:

| Provider / Model                        | Knob                                | Shape                                  |
|-----------------------------------------|-------------------------------------|----------------------------------------|
| Claude Opus 4.7 / Mythos                | `output_config.effort`              | `low`/`medium`/`high`/`xhigh`/`max`    |
| Claude Opus 4.6 / Sonnet 4.6            | `output_config.effort` (+ legacy)   | same (budget_tokens deprecated)        |
| Claude Opus 4.5 and earlier             | `thinking.budget_tokens`            | integer                                |
| Claude Opus 4.7 (agentic loops, beta)   | `output_config.task_budget.total`   | integer ≥ 20,000                       |
| OpenAI o-series                         | `reasoning_effort`                  | `low`/`medium`/`high`                  |
| Gemini 3                                | `thinkingConfig.thinkingLevel`      | `minimal`/`low`/`medium`/`high`        |
| Gemini 2.5                              | `thinkingConfig.thinkingBudget`     | integer (0 off, -1 dynamic)            |

Praxis's 5-tier vocabulary (`none`/`light`/`medium`/`heavy`/`max`) already
maps cleanly onto this five-level axis. That convergence is the foundation
for positioning Praxis as a **cross-provider normalization layer** that
outputs a single tier and translates it to each vendor's native field.

### Integration surfaces already shipped

After this pass, Praxis ships three concrete integration points in the same
repo, each aligned to the observability/gateway ecosystem above:

1. **`hooks/praxis-allocator.py`** — now model-family aware. Emits
   `thinking_config` in the shape the target Claude model accepts, including
   adaptive-only for Opus 4.7 (previously a 400 error).
2. **`lib/effort-mapper.mjs`** — JS twin of the hook's model-family logic.
   Exposes `classifyModelFamily`, `effortForScore`, `buildThinkingConfig`,
   and `allocateForModel(task, model)` for direct integration in
   LangGraph / OpenAI Agents SDK / Agent Framework nodes.
3. **`lib/otel-attrs.mjs`** — OpenInference-compatible span attribute
   helpers (`praxis.complexity_score`, `praxis.tier_chosen`,
   `praxis.reasoning_tokens_used`, `praxis.budget_utilization`,
   `praxis.over_allocated`) that render automatically in Phoenix, Langfuse,
   Helicone, and any OTel collector.
4. **`examples/litellm-callback/`** — ~250-line Python `CustomLogger` that
   turns LiteLLM into a Praxis-aware gateway. Single install lights up every
   observability tool that already integrates with LiteLLM (≈ all of them).

### Thesis (expanded)

| Axis                          | Is it empty? | Who's close? | Why Praxis still owns it |
|-------------------------------|--------------|--------------|--------------------------|
| Policy: prompt → budget       | yes          | RouteLLM (but picks models) | Praxis is budget, not model; online, not calibrated |
| Closed loop: traces → policy  | yes          | nobody       | No observability tool writes back into the request path |
| Cross-provider normalization  | yes          | LiteLLM (mechanism only) | LiteLLM passes through; nobody maps a unified tier across vendors |
| Existential threat            | Anthropic Adaptive Thinking | same model, *coarser* knob | Anthropic moved the integer knob inside the model; meta-decisions (tier selection, task_budget sizing, cross-provider normalization) are still client-side |

The gap is policy, not plumbing — and the policy must be
**per-prompt, per-provider, and feedback-driven**. That's the intersection
Praxis occupies uniquely.

### Evidence provenance (pass 2 — observability and gateways)

Observability/gateway investigation performed via Obscura MCP browser tools on
2026-04-28, covering GitHub READMEs for Portkey, Helicone, Langfuse, Phoenix,
OpenLLMetry, Pezzo, Lunary (404), RouteLLM, Not-Diamond (archived), LiteLLM,
plus docs for Anthropic Extended Thinking / Adaptive Thinking / Effort /
Task Budgets, Gemini Thinking, and OpenInference semantic conventions.
