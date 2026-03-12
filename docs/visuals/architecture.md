# PRAXIS Architecture

## System Flow

```
                         ┌──────────────────────────────────┐
                         │        USER PROMPT INPUT          │
                         └───────────────┬──────────────────┘
                                         │
                          ┌──────────────▼──────────────┐
                          │    praxis-allocator.py       │
                          │    (UserPromptSubmit Hook)   │
                          └──────────────┬──────────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
         ┌──────────▼─────────┐  ┌──────▼───────┐  ┌───────▼────────┐
         │  Keyword Detection  │  │  Complexity   │  │   Signal       │
         │                     │  │  Scoring      │  │   Extraction   │
         │  think → 8192      │  │               │  │                │
         │  megathink → 16384 │  │  Score: 1-10  │  │  keywords      │
         │  ultrathink → 32768│  │               │  │  length        │
         └──────────┬─────────┘  └──────┬───────┘  │  question type  │
                    │                    │          │  structure      │
                    │            ┌───────▼───────┐  └───────┬────────┘
                    │            │ Task Type     │          │
                    │            │ Classifier    ├──────────┘
                    │            └───────┬───────┘
                    │                    │
                    └────────┬───────────┘
                             │
                    ┌────────▼────────┐
                    │ Budget Allocator │
                    │                  │
                    │ Score → Tokens   │
                    │ 1-2  → 0        │
                    │ 3-4  → 2048     │
                    │ 5-6  → 8192     │
                    │ 7-8  → 16384    │
                    │ 9-10 → 32768    │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Cost Tracker    │
                    │                  │
                    │  Log cost        │
                    │  Track savings   │
                    │  Efficiency      │
                    └────────┬────────┘
                             │
                    ┌────────▼────────────────────┐
                    │  MAX_THINKING_TOKENS = N     │
                    │  Applied to Claude API call  │
                    └─────────────────────────────┘
```

## Module Dependency Graph

```
thinking-keywords.mjs ──────────────────────┐
                                             │
complexity-scorer.mjs ─────┐                │
        │                   │                │
        │            budget-allocator.mjs    │
        │                   │                │
        └───────────────────┤                │
                            │                │
                     cost-tracker.mjs        │
                            │                │
                    ┌───────┴────────────────┘
                    │
             praxis-allocator.py
             (mirrors JS logic in Python)
```

## Decision Flow

```
Prompt arrives
    │
    ├─── Has thinking keyword? ──── YES ──→ Use keyword's token budget
    │                                        (keyword_override)
    NO
    │
    ├─── Extract signals (keywords, length, type, structure)
    │
    ├─── Score complexity (weighted formula → 1-10)
    │
    ├─── Classify task type (question/impl/arch/debug/review)
    │
    ├─── Map score to budget tier
    │
    ├─── Check cost limit? ──── YES ──→ Reduce tier if over budget
    │
    NO
    │
    └─── Return { tokens, tier, complexity, cost }
```

## Data Flow for Cost Tracking

```
┌────────────┐    ┌──────────────┐    ┌───────────────┐
│ Each Call   │───▶│ trackCost()  │───▶│  Cost Log     │
│ tokens used │    │ actual cost  │    │  (in-memory)  │
│ model       │    │ max cost     │    │               │
└────────────┘    │ saved        │    └───────┬───────┘
                  └──────────────┘            │
                                     ┌───────▼───────┐
                                     │ getSavings()  │
                                     │ getEfficiency()│
                                     │               │
                                     │ total saved   │
                                     │ % saved       │
                                     │ quality/$     │
                                     └───────────────┘
```
