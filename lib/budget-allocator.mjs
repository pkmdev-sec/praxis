/**
 * PRAXIS — Budget Allocator
 * Allocates thinking tokens based on complexity scores.
 */

import { scoreComplexity, classifyTaskType } from './complexity-scorer.mjs';

// Token budget tiers mapped to complexity score ranges
const BUDGET_TIERS = {
  none:   { range: [1, 2], tokens: 0 },
  light:  { range: [3, 4], tokens: 2048 },
  medium: { range: [5, 6], tokens: 8192 },
  heavy:  { range: [7, 8], tokens: 16384 },
  max:    { range: [9, 10], tokens: 32768 },
};

// Model-specific cost per 1K thinking tokens (USD)
const MODEL_COSTS = {
  // Anthropic thinking-token pricing per 1K tokens (USD). Current as of
  // April 2026; see https://www.anthropic.com/pricing. Opus 4.7 retains
  // Opus 4.x pricing; Mythos Preview is opus-class.
  'claude-opus-4-7':       { thinkingPer1k: 0.06 },
  'claude-opus-4-6':       { thinkingPer1k: 0.06 },
  'claude-opus-4-5':       { thinkingPer1k: 0.06 },
  'claude-mythos-preview': { thinkingPer1k: 0.06 },
  'claude-sonnet-4-6':     { thinkingPer1k: 0.012 },
  'claude-haiku-4-5':      { thinkingPer1k: 0.003 },
};

// In-memory efficiency history
const efficiencyHistory = [];

/**
 * Allocate thinking tokens based on complexity score and model.
 * @param {number} complexityScore - Score from 1-10.
 * @param {string} [model='claude-sonnet-4-6'] - Model identifier.
 * @returns {{ tokens: number, tier: string, model: string }}
 */
export function allocate(complexityScore, model = 'claude-sonnet-4-6') {
  try {
    // Input validation
    if (typeof complexityScore !== 'number' || isNaN(complexityScore)) {
      throw new Error(`Invalid complexityScore: expected number, got ${typeof complexityScore}`);
    }
    if (typeof model !== 'string' || model.trim() === '') {
      throw new Error(`Invalid model: expected non-empty string, got ${model}`);
    }

    // Warn if model is unknown
    if (!MODEL_COSTS[model]) {
      console.warn(`Unknown model '${model}', using claude-sonnet-4-6 pricing as default`);
    }

    const score = Math.max(1, Math.min(10, Math.round(complexityScore)));

    for (const [tier, { range, tokens }] of Object.entries(BUDGET_TIERS)) {
      if (score >= range[0] && score <= range[1]) {
        return { tokens, tier, model };
      }
    }

    // Fallback
    return { tokens: BUDGET_TIERS.medium.tokens, tier: 'medium', model };
  } catch (error) {
    console.error(`Error in allocate: ${error.message}`);
    throw error;
  }
}

/**
 * Get the optimal budget considering a cost limit.
 * @param {string} task - The task/prompt text.
 * @param {number} [costLimit=Infinity] - Max cost in USD for this call.
 * @returns {{ tokens: number, tier: string, estimatedCost: number, model: string, complexity: number }}
 */
export function getOptimalBudget(task, costLimit = Infinity) {
  try {
    // Input validation
    if (typeof task !== 'string') {
      throw new Error(`Invalid task: expected string, got ${typeof task}`);
    }
    if (typeof costLimit !== 'number' || isNaN(costLimit) || costLimit < 0) {
      throw new Error(`Invalid costLimit: expected non-negative number, got ${costLimit}`);
    }

    const complexity = scoreComplexity(task);
    const taskType = classifyTaskType(task);

    // Start with complexity-based allocation using default model
    let model = 'claude-sonnet-4-6';
    let { tokens, tier } = allocate(complexity, model);

    // Calculate estimated cost
    let estimatedCost = calculateCost(tokens, model);

    // If over budget, try reducing tokens first
    if (estimatedCost > costLimit && costLimit !== Infinity) {
      // Try each tier downward
      const tierOrder = ['max', 'heavy', 'medium', 'light', 'none'];
      for (const t of tierOrder) {
        const candidateTokens = BUDGET_TIERS[t].tokens;
        const candidateCost = calculateCost(candidateTokens, model);
        if (candidateCost <= costLimit) {
          tokens = candidateTokens;
          tier = t;
          estimatedCost = candidateCost;
          break;
        }
      }
    }

    return {
      tokens,
      tier,
      estimatedCost,
      model,
      complexity,
      taskType,
    };
  } catch (error) {
    console.error(`Error in getOptimalBudget: ${error.message}`);
    throw error;
  }
}

/**
 * Calculate USD cost for a given token count and model.
 * @param {number} tokens
 * @param {string} model
 * @returns {number}
 */
function calculateCost(tokens, model) {
  // Warn if model is unknown
  if (!MODEL_COSTS[model]) {
    console.warn(`Unknown model '${model}' in calculateCost, using claude-sonnet-4-6 pricing as default`);
  }
  const modelCost = MODEL_COSTS[model] || MODEL_COSTS['claude-sonnet-4-6'];
  return (tokens / 1000) * modelCost.thinkingPer1k;
}

/**
 * Track efficiency of a budget allocation against quality outcome.
 * @param {number} budget - Tokens allocated.
 * @param {number} quality - Quality score 0-10 of the result.
 * @returns {{ efficiency: number, entry: object }}
 */
export function trackEfficiency(budget, quality) {
  try {
    // Input validation
    if (typeof budget !== 'number' || isNaN(budget) || budget < 0) {
      throw new Error(`Invalid budget: expected non-negative number, got ${budget}`);
    }
    if (typeof quality !== 'number' || isNaN(quality)) {
      throw new Error(`Invalid quality: expected number, got ${quality}`);
    }

    const efficiency = budget > 0 ? quality / (budget / 1000) : quality;
    const entry = {
      budget,
      quality,
      efficiency,
      timestamp: Date.now(),
    };
    efficiencyHistory.push(entry);
    return { efficiency, entry };
  } catch (error) {
    console.error(`Error in trackEfficiency: ${error.message}`);
    throw error;
  }
}

/**
 * Get a savings report comparing actual usage vs always-max budgets.
 * @returns {{ totalAllocated: number, maxPossible: number, tokensSaved: number, percentSaved: number, callCount: number, avgEfficiency: number }}
 */
export function getSavingsReport() {
  try {
    if (efficiencyHistory.length === 0) {
      return {
        totalAllocated: 0,
        maxPossible: 0,
        tokensSaved: 0,
        percentSaved: 0,
        callCount: 0,
        avgEfficiency: 0,
      };
    }

    const totalAllocated = efficiencyHistory.reduce((sum, e) => sum + e.budget, 0);
    const maxPossible = efficiencyHistory.length * BUDGET_TIERS.max.tokens;
    const tokensSaved = maxPossible - totalAllocated;
    const percentSaved = maxPossible > 0 ? (tokensSaved / maxPossible) * 100 : 0;
    const avgEfficiency =
      efficiencyHistory.reduce((sum, e) => sum + e.efficiency, 0) / efficiencyHistory.length;

    return {
      totalAllocated,
      maxPossible,
      tokensSaved,
      percentSaved: Math.round(percentSaved * 100) / 100,
      callCount: efficiencyHistory.length,
      avgEfficiency: Math.round(avgEfficiency * 1000) / 1000,
    };
  } catch (error) {
    console.error(`Error in getSavingsReport: ${error.message}`);
    throw error;
  }
}

/**
 * Reset efficiency history (for testing).
 */
export function resetHistory() {
  try {
    efficiencyHistory.length = 0;
  } catch (error) {
    console.error(`Error in resetHistory: ${error.message}`);
    throw error;
  }
}

/**
 * P1 ENHANCEMENT: Calculate average efficiency from history for a complexity range.
 * @param {number} complexityScore - The complexity score to check.
 * @param {number} [range=1] - The +/- range around the score to consider.
 * @returns {number} Average efficiency for that complexity range, or 0 if no data.
 */
function getHistoricalEfficiency(complexityScore, range = 1) {
  if (efficiencyHistory.length === 0) return 0;

  const minScore = complexityScore - range;
  const maxScore = complexityScore + range;

  const relevantEntries = efficiencyHistory.filter(e => {
    const entryScore = e.complexity || 5; // default to medium if not tracked
    return entryScore >= minScore && entryScore <= maxScore;
  });

  if (relevantEntries.length === 0) return 0;

  const avgEfficiency = relevantEntries.reduce((sum, e) => sum + e.efficiency, 0) / relevantEntries.length;
  return avgEfficiency;
}

/**
 * P1 ENHANCEMENT: Adaptive budget allocation based on past quality outcomes.
 * Learns from efficiency history to optimize budget allocation over time.
 *
 * If past allocations at a complexity level had low efficiency (wasted tokens),
 * this will reduce the budget. If they had high efficiency, it maintains or increases.
 *
 * @param {string} task - The task/prompt text.
 * @param {object} [options] - Options for adaptive allocation.
 * @param {number} [options.costLimit=Infinity] - Max cost in USD.
 * @param {number} [options.learningRate=0.2] - How much to adjust based on history (0-1).
 * @param {boolean} [options.enableAdaptation=true] - Enable adaptive learning.
 * @returns {{
 *   tokens: number,
 *   tier: string,
 *   estimatedCost: number,
 *   model: string,
 *   complexity: number,
 *   taskType: string,
 *   originalTokens: number,
 *   adjustment: number,
 *   historicalEfficiency: number,
 *   adapted: boolean
 * }}
 */
export function allocateAdaptive(task, options = {}) {
  try {
    const {
      costLimit = Infinity,
      learningRate = 0.2,
      enableAdaptation = true,
    } = options;

    // Input validation
    if (typeof task !== 'string') {
      throw new Error(`Invalid task: expected string, got ${typeof task}`);
    }
    if (typeof costLimit !== 'number' || isNaN(costLimit) || costLimit < 0) {
      throw new Error(`Invalid costLimit: expected non-negative number, got ${costLimit}`);
    }
    if (typeof learningRate !== 'number' || isNaN(learningRate) || learningRate < 0 || learningRate > 1) {
      throw new Error(`Invalid learningRate: expected number between 0-1, got ${learningRate}`);
    }

    const complexity = scoreComplexity(task);
    const taskType = classifyTaskType(task);

    // Get base allocation
    let model = 'claude-sonnet-4-6';
    let { tokens: originalTokens, tier } = allocate(complexity, model);

    let tokens = originalTokens;
    let adjustment = 0;
    let adapted = false;
    const historicalEfficiency = getHistoricalEfficiency(complexity, 1);

    // Apply adaptive adjustment if enabled and we have history
    if (enableAdaptation && historicalEfficiency > 0) {
      // Efficiency thresholds:
      // < 5: very inefficient (over-allocated)
      // 5-10: acceptable
      // > 10: very efficient (could allocate more)

      if (historicalEfficiency < 5) {
        // Past allocations were inefficient - reduce budget
        adjustment = -Math.floor(tokens * learningRate * 0.5);
      } else if (historicalEfficiency > 15) {
        // Past allocations were very efficient - could increase budget
        adjustment = Math.floor(tokens * learningRate * 0.3);
      }

      tokens = Math.max(0, Math.min(BUDGET_TIERS.max.tokens, tokens + adjustment));

      // Recalculate tier based on adjusted tokens
      for (const [t, { tokens: tierTokens }] of Object.entries(BUDGET_TIERS)) {
        if (tokens === tierTokens) {
          tier = t;
          break;
        }
      }

      adapted = adjustment !== 0;
    }

    // Calculate estimated cost
    let estimatedCost = calculateCost(tokens, model);

    // Apply cost limit constraint
    if (estimatedCost > costLimit && costLimit !== Infinity) {
      const tierOrder = ['max', 'heavy', 'medium', 'light', 'none'];
      for (const t of tierOrder) {
        const candidateTokens = BUDGET_TIERS[t].tokens;
        const candidateCost = calculateCost(candidateTokens, model);
        if (candidateCost <= costLimit) {
          tokens = candidateTokens;
          tier = t;
          estimatedCost = candidateCost;
          break;
        }
      }
    }

    return {
      tokens,
      tier,
      estimatedCost,
      model,
      complexity,
      taskType,
      originalTokens,
      adjustment,
      historicalEfficiency: Math.round(historicalEfficiency * 100) / 100,
      adapted,
    };
  } catch (error) {
    console.error(`Error in allocateAdaptive: ${error.message}`);
    throw error;
  }
}

/**
 * P1 ENHANCEMENT: Enhanced efficiency tracking with complexity score.
 * Allows adaptive allocation to learn from past performance at specific complexity levels.
 * @param {number} budget - Tokens allocated.
 * @param {number} quality - Quality score 0-10 of the result.
 * @param {number} [complexity] - Optional complexity score to track.
 * @returns {{ efficiency: number, entry: object }}
 */
export function trackEfficiencyWithComplexity(budget, quality, complexity) {
  try {
    // Input validation
    if (typeof budget !== 'number' || isNaN(budget) || budget < 0) {
      throw new Error(`Invalid budget: expected non-negative number, got ${budget}`);
    }
    if (typeof quality !== 'number' || isNaN(quality)) {
      throw new Error(`Invalid quality: expected number, got ${quality}`);
    }
    if (complexity !== undefined && (typeof complexity !== 'number' || isNaN(complexity))) {
      throw new Error(`Invalid complexity: expected number or undefined, got ${complexity}`);
    }

    const efficiency = budget > 0 ? quality / (budget / 1000) : quality;
    const entry = {
      budget,
      quality,
      efficiency,
      complexity: complexity || null,
      timestamp: Date.now(),
    };
    efficiencyHistory.push(entry);
    return { efficiency, entry };
  } catch (error) {
    console.error(`Error in trackEfficiencyWithComplexity: ${error.message}`);
    throw error;
  }
}

/**
 * P1 ENHANCEMENT: Get efficiency history with optional filtering.
 * @param {object} [filters] - Optional filters.
 * @param {number} [filters.minComplexity] - Minimum complexity score.
 * @param {number} [filters.maxComplexity] - Maximum complexity score.
 * @param {number} [filters.limit] - Maximum number of entries to return.
 * @returns {object[]} Array of efficiency entries.
 */
export function getEfficiencyHistory(filters = {}) {
  try {
    let results = [...efficiencyHistory];

    if (filters.minComplexity !== undefined) {
      results = results.filter(e => e.complexity && e.complexity >= filters.minComplexity);
    }
    if (filters.maxComplexity !== undefined) {
      results = results.filter(e => e.complexity && e.complexity <= filters.maxComplexity);
    }
    if (filters.limit !== undefined && filters.limit > 0) {
      results = results.slice(-filters.limit);
    }

    return results;
  } catch (error) {
    console.error(`Error in getEfficiencyHistory: ${error.message}`);
    throw error;
  }
}

/**
 * Generate a formatted CLI recommendation for thinking budget.
 * @param {string} prompt - The user prompt to analyze.
 * @param {Object} [options={}] - Options.
 * @param {string} [options.model='claude-sonnet-4-6'] - Target model.
 * @param {number} [options.costLimit=Infinity] - Max cost.
 * @returns {string} Formatted recommendation string for CLI display.
 */
export function getRecommendation(prompt, options = {}) {
  try {
    const { model = 'claude-sonnet-4-6', costLimit = Infinity } = options;

    // Input validation
    if (typeof prompt !== 'string') {
      throw new Error(`Invalid prompt: expected string, got ${typeof prompt}`);
    }

    const budget = getOptimalBudget(prompt, costLimit);

    const complexityBar = '█'.repeat(budget.complexity) + '░'.repeat(10 - budget.complexity);
    const lines = [
      '┌─────────────────────────────────────────┐',
      '│  Praxis Thinking Budget Recommendation  │',
      '├─────────────────────────────────────────┤',
      `│  Complexity:  ${String(budget.complexity).padStart(2)}/10  ${complexityBar.padEnd(12)}│`,
      `│  Task Type:   ${(budget.taskType || 'unknown').padEnd(24)}│`,
      `│  Budget Tier: ${budget.tier.padEnd(24)}│`,
      `│  Tokens:      ${String(budget.tokens).padStart(6).padEnd(24)}│`,
      `│  Model:       ${(budget.model || model).padEnd(24)}│`,
      `│  Est. Cost:   $${budget.estimatedCost.toFixed(4).padEnd(22)}│`,
      '└─────────────────────────────────────────┘',
    ];

    return lines.join('\n');
  } catch (error) {
    console.error(`Error in getRecommendation: ${error.message}`);
    throw error;
  }
}

export { BUDGET_TIERS, MODEL_COSTS };
