# Complexity Scoring

## Overview

The complexity scorer analyzes user prompts and assigns a score from 1-10 that determines how many thinking tokens to allocate.

## Scoring Algorithm

The score is a weighted combination of four signal types:

### 1. Keyword Matching (30%)

Prompts are scanned against four keyword tiers:

| Tier | Score | Example Patterns |
|------|-------|-----------------|
| Simple | 1 | "what is", "define", "explain", "list" |
| Moderate | 4 | "fix", "modify", "implement", "create" |
| Complex | 7 | "design", "architect", "scalable", "distributed" |
| Advanced | 9 | "race condition", "memory leak", "deadlock" |

### 2. Question Type (30%)

The type of question determines expected reasoning depth:

| Type | Score | Detection |
|------|-------|-----------|
| Factual | 1 | "What/Who/Where/When..." questions |
| Explanatory | 3 | "How/Why..." questions |
| Decisional | 4 | "Should/Could/Can..." questions |
| Imperative | 5 | "Implement/Create/Build..." commands |
| Evaluative | 5 | "Review/Check/Audit..." requests |
| Diagnostic | 7 | "Fix/Debug/Solve..." requests |
| Strategic | 8 | "Design/Architect/Plan..." requests |

### 3. Prompt Length (20%)

Longer prompts tend to describe more complex tasks:

| Word Count | Score |
|-----------|-------|
| ≤ 10 | 1 |
| 11-30 | 3 |
| 31-80 | 5 |
| 81-150 | 7 |
| > 150 | 9 |

### 4. Structural Complexity (20%)

Structural elements indicate multi-faceted tasks:

- Code blocks: +2 per block
- Multiple question marks: +1.5 per extra question
- Bullet points: +0.5 per item

## Task Classification

Prompts are also classified into task types, which feed into the final score:

- **Question** (score weight: 2) — Asking for information
- **Implementation** (score weight: 5) — Building or modifying code
- **Review** (score weight: 5) — Evaluating existing code
- **Debugging** (score weight: 7) — Finding and fixing issues
- **Architecture** (score weight: 8) — Designing systems

## Final Score Calculation

```
raw = keywords × 0.3 + length × 0.2 + questionType × 0.3 + structural × 0.2
final = round(raw × 0.6 + taskTypeScore × 0.4)
clamped to [1, 10]
```
