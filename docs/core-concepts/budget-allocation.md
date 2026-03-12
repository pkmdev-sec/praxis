# Budget Allocation

## Overview

The budget allocator translates complexity scores into concrete thinking token budgets, balancing cost against quality.

## Token Budget Tiers

| Complexity | Tier | MAX_THINKING_TOKENS | Typical Cost (Sonnet) |
|-----------|------|--------------------|-----------------------|
| 1-2 | None | 0 | $0.000 |
| 3-4 | Light | 2,048 | $0.025 |
| 5-6 | Medium | 8,192 | $0.098 |
| 7-8 | Heavy | 16,384 | $0.197 |
| 9-10 | Max | 32,768 | $0.393 |

## Cost-Aware Allocation

When a cost limit is specified, the allocator works downward through tiers until finding one that fits within budget:

```
getOptimalBudget("Design a distributed system", costLimit=0.10)
  → Complexity: 7
  → Default: 16,384 tokens ($0.197) — over budget
  → Fallback: 8,192 tokens ($0.098) — within budget ✓
```

## Model Pricing

| Model | Cost per 1K Thinking Tokens |
|-------|---------------------------|
| Claude Opus 4.6 | $0.060 |
| Claude Sonnet 4.6 | $0.012 |
| Claude Haiku 4.5 | $0.003 |

## Efficiency Tracking

The allocator tracks the relationship between budget and output quality:

- **Efficiency ratio** = quality / (tokens / 1000)
- Higher efficiency means good results with fewer tokens
- Over time, this data reveals optimal allocation points

## Savings Calculation

```
savings = (maxPossibleTokens - actualAllocated) / maxPossibleTokens × 100%
```

For a typical mixed workload (40% simple, 30% moderate, 20% complex, 10% advanced):

```
Always-max: 32,768 tokens × 100 calls = 3,276,800 tokens
PRAXIS:     weighted average ≈ 1,200,000 tokens
Savings:    ~63%
```

## Thinking Keyword Integration

When explicit keywords are detected in a prompt, they override the complexity-based allocation:

| Keyword | Token Budget |
|---------|-------------|
| `think` | 8,192 |
| `megathink` | 16,384 |
| `ultrathink` | 32,768 |

User-specified keywords always take precedence over auto-scoring.
