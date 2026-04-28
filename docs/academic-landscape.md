# Academic Landscape: Adaptive Test-Time Compute Allocation (2024–2026)

**Scope.** Published research on *adaptive test-time compute allocation* — the problem Praxis's `lib/complexity-scorer.mjs` + `lib/budget-allocator.mjs` attack. This doc is the academic-layer counterpart to [`competitive-landscape.md`](./competitive-landscape.md), which maps the agent-framework layer (AutoGen, MAF, LangGraph, OpenAI Agents).

**Short answer.** The problem is partially solved for single-turn math/QA; actively being solved for generic tool-use / web agents (Ares, Mar 2026); and **not yet solved for multi-turn coding agents on SWE-bench-class workloads**. That last bucket is the open empirical whitespace Praxis can occupy.

**Method.** Obscura browser MCP fanout across arxiv.org, three parallel explorers, ~35 papers read at abstract + first-intro level, all arxiv IDs verified by primary-source fetch on 2026-04-28.

## Canonical survey

- **Zhang et al. 2025, "A Survey on Test-Time Scaling in LLMs: What, How, Where, and How Well?"** — [arXiv:2503.24235](https://arxiv.org/abs/2503.24235). 4-axis taxonomy, Muennighoff co-author, v3 (May 2025) expands agentic and SFT chapters. **Cite this as the field-overview.**

---

## Cluster 1 — Test-time compute scaling laws

| Paper | arxiv | Headline |
|---|---|---|
| Snell et al. 2024, "Scaling LLM Test-Time Compute Optimally…" | [2408.03314](https://arxiv.org/abs/2408.03314) | Compute-optimal TTS is **>4× more efficient than best-of-N**; a small model + TTS **outperforms a 14× larger model** where the base has non-trivial success rate. |
| Brown et al. 2024, "Large Language Monkeys" | [2407.21787](https://arxiv.org/abs/2407.21787) | Coverage log-linear in samples over 4 orders of magnitude. On **SWE-bench Lite** with DeepSeek-Coder-V2-Instruct: **15.9% → 56%** going from 1 → 250 samples, beating single-sample SOTA of 43%. |
| Sadhukhan et al. 2025, "Kinetics: Rethinking Test-Time Scaling Laws" | [2506.05333](https://arxiv.org/abs/2506.05333) | Memory access (not FLOPs) dominates TTS cost. Sparse attention **>60pt gain on AIME in low-cost regime**. Important rebuttal to Snell-era optimism. |

**Consensus**: monotonic gains on easy/medium problems, flat-or-negative on hard problems past a crossover point (overthinking literature: [2604.10739](https://arxiv.org/abs/2604.10739), [2604.06787](https://arxiv.org/abs/2604.06787)). **Agent-tested**: Brown on SWE-bench Lite only.

## Cluster 2 — Pre-hoc difficulty / budget prediction (Praxis's core claim)

| Paper | arxiv | Headline |
|---|---|---|
| Damani et al. 2024, "Learning How Hard to Think" | [2410.04707](https://arxiv.org/abs/2410.04707) | Input-adaptive best-of-k and model routing. **~50% compute reduction at no quality cost, or +10% accuracy at fixed budget** on math/TACO/chat. Single-turn. |
| Brown, Muppidi, Shahout 2026, "Predictive Scheduling" | [2602.01237](https://arxiv.org/abs/2602.01237) | LoRA classifier → greedy batch allocator. **+7.9pp over uniform** at matched token cost on GSM8K, **but only in the 16–96 tok regime**; above that, adaptive loses to uniform because prediction errors compound. Discrete 3-class beats continuous regression. |
| Liang et al. 2025, "ThinkSwitcher" | [2505.14183](https://arxiv.org/abs/2505.14183) | Lightweight switching module on a single LRM. **20–30% compute reduction** with high accuracy on complex tasks. |
| Fernandez et al. 2025 (ICLR 2026), "RADAR" | [2509.25426](https://arxiv.org/abs/2509.25426) | IRT-based routing over (model, budget) pairs with query-difficulty/model-ability parameters. SOTA on 8 reasoning benchmarks. |

Also in-cluster: DynaThink [2407.01009](https://arxiv.org/abs/2407.01009), SCOPE [2601.22323](https://arxiv.org/abs/2601.22323), Z1 [2504.00810](https://arxiv.org/abs/2504.00810), R-4B [2508.21113](https://arxiv.org/abs/2508.21113), OThink-R1 [2506.02397](https://arxiv.org/abs/2506.02397), Rational Metareasoning [2410.05563](https://arxiv.org/abs/2410.05563).

**Open**: pre-hoc predictors systematically fail at high budgets on hard problems — exactly where TTS matters. **Agent-tested**: none.

## Cluster 3 — Budget forcing / length control

- **Muennighoff et al. 2025, "s1: Simple test-time scaling"** — [arXiv:2501.19393](https://arxiv.org/abs/2501.19393). SFT on 1K samples + budget forcing (append "Wait" or force `</think>`). Qwen2.5-32B **exceeds o1-preview by up to 27%** on MATH/AIME24; budget-forcing scaling boosts AIME24 **50% → 57%**.
- **OTC-PO (Wang et al. 2025)** — [arXiv:2504.14870](https://arxiv.org/abs/2504.14870). RL with tool-cost reward for TIR agents. **−68.3% tool calls, +215% productivity, matched accuracy.** Closest published "FrugalGPT for agents."
- Length-control siblings: L1/OThink-R1/R-4B.

## Cluster 4 — Model routing

- **RouteLLM (Ong et al. 2024)** — [arXiv:2406.18665](https://arxiv.org/abs/2406.18665). Preference-data router over strong/weak LLM pair. **>2× cost reduction** without quality loss; transferable across model pairs.
- **FrugalGPT (Chen et al. 2023)** — [arXiv:2305.05176](https://arxiv.org/abs/2305.05176). Learned cascade. **Match GPT-4 at up to 98% cost reduction, or +4% accuracy at matched cost.**
- AutoMix [2310.12963](https://arxiv.org/abs/2310.12963), Hybrid LLM [2404.14618](https://arxiv.org/abs/2404.14618), Zooter [2311.08692](https://arxiv.org/abs/2311.08692), speculative decoding [2211.17192](https://arxiv.org/abs/2211.17192) (2–3× speedup, identical outputs — the only production-mature cost-routing primitive).

**Agent-tested**: none publish "RouteLLM on SWE-bench."

## Cluster 5 — Self-consistency with adaptive k

- **Adaptive-Consistency (Aggarwal et al., EMNLP 2023)** — [arXiv:2305.11860](https://arxiv.org/abs/2305.11860). Dirichlet stopping rule over 17 reasoning/coding datasets. **Up to 7.9× sample reduction at <0.1% average accuracy drop.**
- ESC [2401.10480](https://arxiv.org/abs/2401.10480), Path-Consistency [2409.01281](https://arxiv.org/abs/2409.01281), RASC [2408.17017](https://arxiv.org/abs/2408.17017), SeerSC [2511.09345](https://arxiv.org/abs/2511.09345).

Effectively **solved** for single-turn QA. Agent version unexplored.

## Cluster 6 — Prompt compression

- **LLMLingua (Jiang et al., EMNLP 2023)** — [arXiv:2310.05736](https://arxiv.org/abs/2310.05736). Coarse-to-fine compression with budget controller. **Up to 20× compression with little performance loss** on GSM8K/BBH/ShareGPT.
- LongLLMLingua [2310.06839](https://arxiv.org/abs/2310.06839), LLMLingua-2 [2403.12968](https://arxiv.org/abs/2403.12968), Selective Context [2304.12102](https://arxiv.org/abs/2304.12102).

Mostly solved for static prompts; open for trajectory-level agent contexts.

## Cluster 7 — Uncertainty-routed reasoning

- **Self-Route (Li et al., EMNLP 2024 industry)** — [arXiv:2407.16833](https://arxiv.org/abs/2407.16833). Scope is **narrower than the cluster name** suggests: self-reflection → RAG vs long-context LLM routing. ~39% of LC cost at matched quality.
- Dekoninck et al. [2410.10347](https://arxiv.org/abs/2410.10347) — conformal cascades. Confidence-Driven [2502.11021](https://arxiv.org/abs/2502.11021). Self-REF [2410.13284](https://arxiv.org/abs/2410.13284). SRLM [2603.15653](https://arxiv.org/abs/2603.15653).

> ⚠️ **"Zhang 2026, Recursive Language Models Meet Uncertainty"** — could not verify on arxiv (author index search empty). **Do not cite** without primary-source confirmation. Closest real paper is SRLM `2603.15653`.

## Cluster 8 — Coding-agent compute allocation ⭐

- **Agentless (Xia et al. 2024)** — [arXiv:2407.01489](https://arxiv.org/abs/2407.01489). 3-phase localize → repair → validate. **32.00% SWE-bench Lite, 96 fixes, $0.70/instance** — the canonical cheap baseline.
- **Ares (Yang et al., Mar 2026)** — [arXiv:2603.07915](https://arxiv.org/abs/2603.07915). **Per-step** reasoning-effort router (high/med/low) for LLM agents. **52.7% reasoning-token reduction** on TAU-Bench, BrowseComp-Plus, WebArena with minimal accuracy loss. **Not SWE-bench.** Closest Praxis competitor conceptually.
- SWE-agent [2405.15793](https://arxiv.org/abs/2405.15793), OpenHands [2407.16741](https://arxiv.org/abs/2407.16741), CodeAct [2402.01030](https://arxiv.org/abs/2402.01030) — ACI frameworks, no cost-routing policy.
- Domain-level TTS on SWE-bench: CodeMonkeys [2501.14723](https://arxiv.org/abs/2501.14723), Satori-SWE [2505.23604](https://arxiv.org/abs/2505.23604), OSCA [2410.22480](https://arxiv.org/abs/2410.22480) — none do per-instance pre-hoc difficulty prediction.

---

## Genuine whitespace (where no published method does well)

1. **Per-instance pre-hoc difficulty prediction for long-horizon coding agents** (SWE-bench Verified, Aider Polyglot, τ-bench). Damani does single-turn TACO; Ares does per-step on web/tool agents; OSCA does domain-level. **No published work does per-instance tiered thinking-budget for a production coding agent.**
2. **High-budget regime for adaptive allocation** — Predictive Scheduling's own crossover point. Unsolved.
3. **Calibrated abstention-aware routers** — current routers are classifiers, not conformal predictors with "I don't know → escalate."
4. **Budget forcing × model routing** composition.
5. **Trajectory-level cost accumulation** — routing per-query is easy; per-trajectory, where early cheap decisions pollute downstream state, is unsolved.
6. **Joint-training a model with its budget predictor** — adaptive budget *curricula* rather than allocation at inference only.
7. **Agent-benchmark routing numbers** — nobody has published "RouteLLM-style routing on SWE-bench at X% cost."

## Relevance to Praxis

| Layer | Who's there | Praxis position |
|---|---|---|
| Framework plumbing (`thinking={...}`) | AutoGen, MAF, LangGraph, OpenAI Agents | empty policy quadrant — see [competitive-landscape.md](./competitive-landscape.md) |
| Scoring function (prompt → difficulty) | NVIDIA NemoCurator, Damani, RouteLLM | rule-based alternative; NemoCurator adapter is a natural v2 path |
| Policy (score → budget) for coding agents | **no published work** | Praxis's claim |
| Cost-aware agent RL | OTC-PO (tool calls), Ares (per-step web/tool) | distinct axes |

**Strongest defensible framing for Praxis**: per-prompt tiered thinking-budget policy deployed in a production Claude Code coding-agent loop — occupies the intersection of (coding agent, per-instance pre-hoc, rule-based-deployable) that Damani/Ares/Predictive-Scheduling each miss on one of the three axes.

**Runway**: Ares dropped Mar 2026, Predictive Scheduling Feb 2026 — the academic whitespace narrows monthly. The framework-layer whitespace documented in `competitive-landscape.md` is wider and slower-moving, so **lead with the framework gap** and use this academic brief as supporting citation.

## Priority next empirical moves

1. **SWE-bench Verified**: Praxis-on vs Praxis-off cost-accuracy Pareto curve. Single most defensible unpublished result available.
2. **Aider Polyglot**: same, on a less-saturated benchmark.
3. **Scorer ablation**: rule-based vs NemoCurator adapter vs small learned classifier.

## Evidence provenance

Research performed 2026-04-28 via Obscura MCP `browser_fetch` against arxiv.org abstract pages. All arxiv IDs listed verified by primary-source fetch. Parallel RLM fanout: 3 explorer sub-agents over 8 topic clusters. Unverified citations explicitly flagged.
