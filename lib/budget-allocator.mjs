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
  'claude-opus-4-6':   { thinkingPer1k: 0.06 },
  'claude-sonnet-4-6': { thinkingPer1k: 0.012 },
  'claude-haiku-4-5':  { thinkingPer1k: 0.003 },
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
  const score = Math.max(1, Math.min(10, Math.round(complexityScore)));

  for (const [tier, { range, tokens }] of Object.entries(BUDGET_TIERS)) {
    if (score >= range[0] && score <= range[1]) {
      return { tokens, tier, model };
    }
  }

  // Fallback
  return { tokens: BUDGET_TIERS.medium.tokens, tier: 'medium', model };
}

/**
 * Get the optimal budget considering a cost limit.
 * @param {string} task - The task/prompt text.
 * @param {number} [costLimit=Infinity] - Max cost in USD for this call.
 * @returns {{ tokens: number, tier: string, estimatedCost: number, model: string, complexity: number }}
 */
export function getOptimalBudget(task, costLimit = Infinity) {
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
}

/**
 * Calculate USD cost for a given token count and model.
 * @param {number} tokens
 * @param {string} model
 * @returns {number}
 */
function calculateCost(tokens, model) {
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
  const efficiency = budget > 0 ? quality / (budget / 1000) : quality;
  const entry = {
    budget,
    quality,
    efficiency,
    timestamp: Date.now(),
  };
  efficiencyHistory.push(entry);
  return { efficiency, entry };
}

/**
 * Get a savings report comparing actual usage vs always-max budgets.
 * @returns {{ totalAllocated: number, maxPossible: number, tokensSaved: number, percentSaved: number, callCount: number, avgEfficiency: number }}
 */
export function getSavingsReport() {
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
}

/**
 * Reset efficiency history (for testing).
 */
export function resetHistory() {
  efficiencyHistory.length = 0;
}

export { BUDGET_TIERS, MODEL_COSTS };
