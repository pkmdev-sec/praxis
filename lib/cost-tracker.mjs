/**
 * PRAXIS — Cost Tracker
 * Tracks thinking token costs and calculates savings/efficiency.
 */

// Model pricing: cost per 1K thinking tokens (USD)
const THINKING_COSTS = {
  'claude-opus-4-6':   0.060,
  'claude-sonnet-4-6': 0.012,
  'claude-haiku-4-5':  0.003,
};

const MAX_THINKING_TOKENS = 32768;

// In-memory cost log
const costLog = [];

/**
 * Log the cost of thinking tokens used for a single call.
 * @param {number} thinkingTokens - Number of thinking tokens used.
 * @param {string} [model='claude-sonnet-4-6'] - Model identifier.
 * @returns {{ cost: number, maxCost: number, saved: number, entry: object }}
 */
export function trackThinkingCost(thinkingTokens, model = 'claude-sonnet-4-6') {
  const rate = THINKING_COSTS[model] || THINKING_COSTS['claude-sonnet-4-6'];
  const cost = (thinkingTokens / 1000) * rate;
  const maxCost = (MAX_THINKING_TOKENS / 1000) * rate;
  const saved = maxCost - cost;

  const entry = {
    thinkingTokens,
    model,
    cost: Math.round(cost * 1000000) / 1000000,
    maxCost: Math.round(maxCost * 1000000) / 1000000,
    saved: Math.round(saved * 1000000) / 1000000,
    timestamp: Date.now(),
  };

  costLog.push(entry);

  return {
    cost: entry.cost,
    maxCost: entry.maxCost,
    saved: entry.saved,
    entry,
  };
}

/**
 * Calculate total savings from not using maximum thinking budget on every call.
 * @returns {{ totalActualCost: number, totalMaxCost: number, totalSaved: number, percentSaved: number, callCount: number }}
 */
export function getThinkingSavings() {
  if (costLog.length === 0) {
    return {
      totalActualCost: 0,
      totalMaxCost: 0,
      totalSaved: 0,
      percentSaved: 0,
      callCount: 0,
    };
  }

  const totalActualCost = costLog.reduce((sum, e) => sum + e.cost, 0);
  const totalMaxCost = costLog.reduce((sum, e) => sum + e.maxCost, 0);
  const totalSaved = totalMaxCost - totalActualCost;
  const percentSaved = totalMaxCost > 0 ? (totalSaved / totalMaxCost) * 100 : 0;

  return {
    totalActualCost: round6(totalActualCost),
    totalMaxCost: round6(totalMaxCost),
    totalSaved: round6(totalSaved),
    percentSaved: Math.round(percentSaved * 100) / 100,
    callCount: costLog.length,
  };
}

/**
 * Calculate quality per thinking dollar.
 * Requires quality scores to be tracked externally and passed in.
 * @param {{ quality: number, cost: number }[]} [qualityData] - Array of quality/cost pairs. If omitted, uses cost log with assumed quality of 7.
 * @returns {{ avgQualityPerDollar: number, bestRatio: number, worstRatio: number, dataPoints: number }}
 */
export function getThinkingEfficiency(qualityData) {
  const data = qualityData || costLog.map(e => ({ quality: 7, cost: e.cost }));

  if (data.length === 0) {
    return { avgQualityPerDollar: 0, bestRatio: 0, worstRatio: 0, dataPoints: 0 };
  }

  const ratios = data
    .filter(d => d.cost > 0)
    .map(d => d.quality / d.cost);

  if (ratios.length === 0) {
    return { avgQualityPerDollar: Infinity, bestRatio: Infinity, worstRatio: Infinity, dataPoints: data.length };
  }

  const avgQualityPerDollar = ratios.reduce((a, b) => a + b, 0) / ratios.length;

  return {
    avgQualityPerDollar: Math.round(avgQualityPerDollar * 100) / 100,
    bestRatio: Math.round(Math.max(...ratios) * 100) / 100,
    worstRatio: Math.round(Math.min(...ratios) * 100) / 100,
    dataPoints: data.length,
  };
}

/**
 * Get the full cost log.
 * @returns {object[]}
 */
export function getCostLog() {
  return [...costLog];
}

/**
 * Reset the cost log (for testing).
 */
export function resetCostLog() {
  costLog.length = 0;
}

function round6(n) {
  return Math.round(n * 1000000) / 1000000;
}

export { THINKING_COSTS, MAX_THINKING_TOKENS };
