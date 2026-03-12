![Praxis Banner](assets/banner.svg)

<p align="center">
  <strong>Allocate thinking tokens intelligently. Save cost. Preserve quality.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.0-f59e0b?style=flat-square" alt="Version"/>
  <img src="https://img.shields.io/badge/node-%3E%3D18-4338ca?style=flat-square" alt="Node"/>
  <img src="https://img.shields.io/badge/license-MIT-818cf8?style=flat-square" alt="License"/>
  <img src="https://img.shields.io/badge/tests-78%20passed-22c55e?style=flat-square" alt="Tests"/>
</p>

---

## Why Praxis?

From Ancient Greek *πρᾶξις* (praxis), meaning the **practical application of theory**. In Aristotelian philosophy, praxis represented the bridge between abstract knowledge (*theoria*) and productive craft (*poiesis*) — the act of turning understanding into purposeful action.

PRAXIS embodies this philosophical tradition. Claude's extended thinking capability is powerful but expensive — raw *theoria* without discipline. Praxis transforms this into optimized action: analyzing each task's true complexity, allocating precisely the thinking budget needed, and eliminating wasteful over-computation. It is the bridge between unlimited thinking and practical efficiency.

## What is PRAXIS?

PRAXIS dynamically allocates Claude's thinking token budget based on task complexity. Instead of using maximum thinking tokens for every request (expensive), or none at all (lower quality for hard tasks), PRAXIS scores each prompt and assigns the optimal budget.

**The result:** Same quality on hard tasks, massive savings on simple ones.

```
Simple question  →  0 tokens      →  $0.00
Code modification →  2,048 tokens  →  $0.02
Architecture task →  16,384 tokens →  $0.18
Complex debugging →  32,768 tokens →  $0.37
```

## How It Works

<p align="center">
  <img src="docs/visuals/architecture-diagram.svg" alt="PRAXIS Architecture Diagram" width="900"/>
</p>

### Complexity Scoring

Prompts are scored 1-10 using multiple signals:

| Signal | Weight | Description |
|--------|--------|-------------|
| Keywords | 30% | Detected task-related keywords |
| Question Type | 30% | Factual, strategic, diagnostic, etc. |
| Length | 20% | Word count as complexity proxy |
| Structure | 20% | Code blocks, multiple questions |

### Budget Tiers

| Score | Tier | Tokens | Keyword |
|-------|------|--------|---------|
| 1-2 | None | 0 | — |
| 3-4 | Light | 2,048 | `think` |
| 5-6 | Medium | 8,192 | `think` |
| 7-8 | Heavy | 16,384 | `megathink` |
| 9-10 | Max | 32,768 | `ultrathink` |

## Installation

```bash
git clone https://github.com/pkmdev-sec/praxis.git
cd praxis
npm install
```

### As a Claude Code Hook

Add to your Claude Code settings (`~/.claude/settings.json`):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "command": "python3 ~/praxis/hooks/praxis-allocator.py"
      }
    ]
  }
}
```

## Usage

### JavaScript API

```javascript
import { scoreComplexity } from './lib/complexity-scorer.mjs';
import { allocate, getOptimalBudget, getRecommendation } from './lib/budget-allocator.mjs';
import { detectThinkingLevel, suggestLevel } from './lib/thinking-keywords.mjs';
import { trackThinkingCost, getThinkingSavings, generateSavingsReport } from './lib/cost-tracker.mjs';

// Score a prompt
const score = scoreComplexity('Design a distributed cache system');
// → 7

// Allocate tokens
const budget = allocate(score);
// → { tokens: 16384, tier: 'heavy', model: 'claude-sonnet-4-6' }

// Or get optimal budget with cost limit
const optimal = getOptimalBudget('Fix the login bug', 0.05);
// → { tokens: 2048, tier: 'light', estimatedCost: 0.024, ... }

// Get formatted CLI recommendation
const recommendation = getRecommendation('Implement OAuth2 authentication');
console.log(recommendation);

// Detect existing thinking keywords
const level = detectThinkingLevel('ultrathink about this problem');
// → { keyword: 'ultrathink', level: 'maximum', tokens: 32768 }

// Track costs and savings
trackThinkingCost(2048, 'claude-sonnet-4-6');
const savings = getThinkingSavings();
// → { totalSaved: 0.368, percentSaved: 93.75, ... }

// Generate formatted savings report
const report = generateSavingsReport();
console.log(report);
```

### Python Hook (Standalone)

```bash
echo '{"prompt": "Design a microservice architecture"}' | python3 hooks/praxis-allocator.py
# → {"max_thinking_tokens": 16384, "complexity_score": 7, "decision": "auto_scored"}
```

## Examples

PRAXIS includes practical examples demonstrating real-world usage:

### 1. Session Optimizer

**File:** [`examples/optimize-session.mjs`](examples/optimize-session.mjs)

Simulates a complete coding session with 8 diverse tasks, showing how Praxis optimizes thinking token allocation across simple and complex prompts. Demonstrates:

- Complexity scoring for varied task types
- Automatic tier selection and budget allocation
- Session-wide token and cost savings tracking
- Efficiency metrics across multiple API calls

**Run it:**
```bash
node examples/optimize-session.mjs
```

**Sample output:**
```
=== Praxis Session Optimizer ===

--- Analyzing Tasks ---

Task                                                        Score  Tier        Tokens   Cost
----------------------------------------------------------------------------------------------------
  Fix the typo in the README file                            3/10  light           2048   think
  Add input validation to the user registration form usi     5/10  medium          8192   think
  Design a distributed caching architecture with Redis c     8/10  heavy          16384   megathink
  What does the formatDate function do?                      1/10  none               0   none
  Refactor the authentication module to support OAuth2 w     6/10  medium          8192   think
  Run the test suite                                         1/10  none               0   none
  Implement a real-time collaboration system using CRDTs     9/10  max            32768   ultrathink
  Update the copyright year in the footer component          3/10  light           2048   think

--- Session Savings Report ---

  Total allocated:   69,632 tokens
  Max possible:      262,144 tokens
  Tokens saved:      192,512 tokens
  Percent saved:     73.4%
  Calls optimized:   8
  Avg efficiency:    93.2%
```

### 2. Complexity Demo

**File:** [`examples/complexity-demo.mjs`](examples/complexity-demo.mjs)

Explores the complexity scoring engine in depth. Shows how Praxis analyzes different signal types (keywords, length, question type, structure) and assigns scores. Demonstrates:

- Budget tier reference table
- Thinking keyword mappings
- Diverse prompt analysis (simple to complex)
- Multi-signal scoring breakdown
- Code-specific complexity analysis

**Run it:**
```bash
node examples/complexity-demo.mjs
```

**Sample output:**
```
=== Praxis Complexity Scoring Demo ===

--- Budget Tiers ---

  none         0 tokens
  light     2048 tokens
  medium    8192 tokens
  heavy    16384 tokens
  max      32768 tokens

--- Thinking Keywords ---

  think        → 8192 tokens (standard)
  megathink    → 16384 tokens (deep)
  ultrathink   → 32768 tokens (maximum)

--- Prompt Analysis ---

  "What time is it?"
    Type: question  |  Score: 1/10  |  Tier: none  |  Tokens: 0
    Signals: keywords=1.0, length=1.0, question=1.0, structure=1.0

  "Design a microservices architecture with event sourcing and CQRS"
    Type: architecture  |  Score: 8/10  |  Tier: heavy  |  Tokens: 16384
    Signals: keywords=7.0, length=5.0, question=8.0, structure=1.0
```

## CLI Recommendations

Use `getRecommendation()` to generate formatted budget recommendations for CLI display:

```javascript
import { getRecommendation } from './lib/budget-allocator.mjs';

const prompt = 'Implement OAuth2 authentication with PKCE flow';
console.log(getRecommendation(prompt));
```

**Output:**
```
┌─────────────────────────────────────────┐
│  Praxis Thinking Budget Recommendation  │
├─────────────────────────────────────────┤
│  Complexity:   6/10  ██████░░░░          │
│  Task Type:   implementation            │
│  Budget Tier: medium                    │
│  Tokens:        8192                    │
│  Model:       claude-sonnet-4-6         │
│  Est. Cost:   $0.0983                   │
└─────────────────────────────────────────┘
```

The visual complexity bar and structured layout make it easy to understand budget allocation at a glance.

## Savings Report

Use `generateSavingsReport()` to create formatted savings summaries for CLI display:

```javascript
import { generateSavingsReport, trackThinkingCost } from './lib/cost-tracker.mjs';

// Track some costs first
trackThinkingCost(2048, 'claude-sonnet-4-6');
trackThinkingCost(8192, 'claude-sonnet-4-6');
trackThinkingCost(0, 'claude-sonnet-4-6');
trackThinkingCost(16384, 'claude-sonnet-4-6');

console.log(generateSavingsReport());
```

**Output:**
```
╔══════════════════════════════════════════╗
║        Praxis Savings Report             ║
╠══════════════════════════════════════════╣
║  Total API Calls:           4            ║
║  Actual Cost:        $0.3174             ║
║  Without Praxis:     $1.5728             ║
║  Money Saved:        $1.2554             ║
║  Savings Rate:         79.8%             ║
╠══════════════════════════════════════════╣
║  Tier Distribution:                      ║
║    none       ████                  25%  ║
║    light      ████                  25%  ║
║    medium     ████                  25%  ║
║    heavy      ████                  25%  ║
╚══════════════════════════════════════════╝
```

The report includes:
- Total cost vs. maximum-budget baseline
- Percentage and dollar savings
- Visual tier distribution showing allocation patterns

## Budget Tiers Reference

Praxis uses five budget tiers based on complexity scores:

| Tier   | Complexity | Tokens | Cost (Sonnet) | Use Case                          | Keyword      |
|--------|------------|--------|---------------|-----------------------------------|--------------|
| None   | 1-2        | 0      | $0.00         | Trivial queries, simple lookups   | —            |
| Light  | 3-4        | 2,048  | $0.02         | Basic edits, small fixes          | `think`      |
| Medium | 5-6        | 8,192  | $0.10         | Standard implementation tasks     | `think`      |
| Heavy  | 7-8        | 16,384 | $0.20         | Complex refactoring, architecture | `megathink`  |
| Max    | 9-10       | 32,768 | $0.39         | Advanced debugging, system design | `ultrathink` |

**Cost calculations** are based on Claude Sonnet 4.6 thinking token pricing ($0.012 per 1K tokens). Actual costs vary by model:

- **Claude Opus 4.6:** $0.06 per 1K thinking tokens
- **Claude Sonnet 4.6:** $0.012 per 1K thinking tokens (default)
- **Claude Haiku 4.5:** $0.003 per 1K thinking tokens

**Tier selection is automatic** based on multi-signal complexity analysis, but can be manually overridden using thinking keywords in prompts.

## Modules

| Module | Description |
|--------|-------------|
| `lib/complexity-scorer.mjs` | Scores prompt complexity 1-10 |
| `lib/budget-allocator.mjs` | Maps scores to token budgets |
| `lib/thinking-keywords.mjs` | Manages think/megathink/ultrathink |
| `lib/cost-tracker.mjs` | Tracks spending and savings |
| `hooks/praxis-allocator.py` | Claude Code UserPromptSubmit hook |

## Testing

```bash
npm test
```

78 tests across 5 suites covering all modules and the Python hook.

## Project Structure

```
praxis/
├── lib/
│   ├── complexity-scorer.mjs    # Complexity scoring engine
│   ├── budget-allocator.mjs     # Token budget allocation
│   ├── thinking-keywords.mjs    # Thinking keyword management
│   └── cost-tracker.mjs         # Cost tracking and savings
├── hooks/
│   └── praxis-allocator.py      # Claude Code hook
├── tests/
│   ├── complexity-scorer.test.mjs
│   ├── budget-allocator.test.mjs
│   ├── thinking-keywords.test.mjs
│   ├── cost-tracker.test.mjs
│   └── praxis-allocator.test.mjs
├── assets/
│   └── banner.svg
├── docs/
│   ├── core-concepts/
│   │   ├── complexity-scoring.md
│   │   └── budget-allocation.md
│   └── visuals/
│       ├── architecture.md
│       └── architecture-diagram.svg
└── README.md
```

## License

MIT — see [LICENSE](LICENSE)
