/**
 * PRAXIS — Cost Tracker
 * Tracks thinking token costs and calculates savings/efficiency.
 */

import { MODEL_COSTS } from './budget-allocator.mjs';

// Convert MODEL_COSTS to THINKING_COSTS format for backwards compatibility
const THINKING_COSTS = Object.fromEntries(
  Object.entries(MODEL_COSTS).map(([model, { thinkingPer1k }]) => [model, thinkingPer1k])
);

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
  try {
    // Input validation
    if (typeof thinkingTokens !== 'number' || isNaN(thinkingTokens) || thinkingTokens < 0) {
      throw new Error(`Invalid thinkingTokens: expected non-negative number, got ${thinkingTokens}`);
    }
    if (typeof model !== 'string' || model.trim() === '') {
      throw new Error(`Invalid model: expected non-empty string, got ${model}`);
    }

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
  } catch (error) {
    console.error(`Error in trackThinkingCost: ${error.message}`);
    throw error;
  }
}

/**
 * Calculate total savings from not using maximum thinking budget on every call.
 * @returns {{ totalActualCost: number, totalMaxCost: number, totalSaved: number, percentSaved: number, callCount: number }}
 */
export function getThinkingSavings() {
  try {
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
  } catch (error) {
    console.error(`Error in getThinkingSavings: ${error.message}`);
    throw error;
  }
}

/**
 * Calculate quality per thinking dollar.
 * Requires quality scores to be tracked externally and passed in.
 * @param {{ quality: number, cost: number }[]} [qualityData] - Array of quality/cost pairs. If omitted, uses cost log with assumed quality of 7.
 * @returns {{ avgQualityPerDollar: number, bestRatio: number, worstRatio: number, dataPoints: number }}
 */
export function getThinkingEfficiency(qualityData) {
  try {
    // Input validation
    if (qualityData !== undefined && !Array.isArray(qualityData)) {
      throw new Error(`Invalid qualityData: expected array or undefined, got ${typeof qualityData}`);
    }

    const data = qualityData || costLog.map(e => ({ quality: 7, cost: e.cost }));

    if (data.length === 0) {
      return { avgQualityPerDollar: 0, bestRatio: 0, worstRatio: 0, dataPoints: 0 };
    }

    const ratios = data
      .filter(d => d.cost > 0)
      .map(d => d.quality / d.cost);

    // Fix: when all costs are 0, return 0 instead of Infinity (which breaks JSON serialization)
    if (ratios.length === 0) {
      return { avgQualityPerDollar: 0, bestRatio: 0, worstRatio: 0, dataPoints: data.length };
    }

    const avgQualityPerDollar = ratios.reduce((a, b) => a + b, 0) / ratios.length;

    return {
      avgQualityPerDollar: Math.round(avgQualityPerDollar * 100) / 100,
      bestRatio: Math.round(Math.max(...ratios) * 100) / 100,
      worstRatio: Math.round(Math.min(...ratios) * 100) / 100,
      dataPoints: data.length,
    };
  } catch (error) {
    console.error(`Error in getThinkingEfficiency: ${error.message}`);
    throw error;
  }
}

/**
 * Get the full cost log.
 * @returns {object[]}
 */
export function getCostLog() {
  try {
    return [...costLog];
  } catch (error) {
    console.error(`Error in getCostLog: ${error.message}`);
    throw error;
  }
}

/**
 * Reset the cost log (for testing).
 */
export function resetCostLog() {
  try {
    costLog.length = 0;
  } catch (error) {
    console.error(`Error in resetCostLog: ${error.message}`);
    throw error;
  }
}

function round6(n) {
  return Math.round(n * 1000000) / 1000000;
}

/**
 * P1 ENHANCEMENT: Generate a comprehensive comparison report showing
 * actual costs vs. baseline scenarios (no optimization, always-max, etc.).
 * Demonstrates the value of PRAXIS optimization.
 *
 * @param {object} [options] - Report options.
 * @param {boolean} [options.includePerCall=false] - Include per-call breakdown.
 * @returns {{
 *   actualCosts: { total: number, average: number, callCount: number },
 *   noOptimizationCosts: { total: number, average: number, description: string },
 *   alwaysMaxCosts: { total: number, average: number, description: string },
 *   savings: {
 *     vsNoOptimization: { amount: number, percent: number },
 *     vsAlwaysMax: { amount: number, percent: number }
 *   },
 *   recommendations: string[],
 *   perCallBreakdown?: object[]
 * }}
 */
export function getComparisonReport(options = {}) {
  try {
    const { includePerCall = false } = options;

    if (costLog.length === 0) {
      return {
        actualCosts: { total: 0, average: 0, callCount: 0 },
        noOptimizationCosts: { total: 0, average: 0, description: 'No optimization (typical default: 16384 tokens)' },
        alwaysMaxCosts: { total: 0, average: 0, description: 'Always maximum (32768 tokens)' },
        savings: {
          vsNoOptimization: { amount: 0, percent: 0 },
          vsAlwaysMax: { amount: 0, percent: 0 },
        },
        recommendations: ['No data yet. Start tracking costs to see savings.'],
        perCallBreakdown: includePerCall ? [] : undefined,
      };
    }

    // Calculate actual costs
    const totalActual = costLog.reduce((sum, e) => sum + e.cost, 0);
    const avgActual = totalActual / costLog.length;

    // Calculate "no optimization" baseline (assume 16384 tokens per call - typical heavy default)
    const NO_OPT_TOKENS = 16384;
    const totalNoOpt = costLog.reduce((sum, e) => {
      const rate = THINKING_COSTS[e.model] || THINKING_COSTS['claude-sonnet-4-6'];
      return sum + (NO_OPT_TOKENS / 1000) * rate;
    }, 0);
    const avgNoOpt = totalNoOpt / costLog.length;

    // Calculate always-max costs
    const totalMax = costLog.reduce((sum, e) => sum + e.maxCost, 0);
    const avgMax = totalMax / costLog.length;

    // Calculate savings
    const savingsVsNoOpt = totalNoOpt - totalActual;
    const percentVsNoOpt = totalNoOpt > 0 ? (savingsVsNoOpt / totalNoOpt) * 100 : 0;

    const savingsVsMax = totalMax - totalActual;
    const percentVsMax = totalMax > 0 ? (savingsVsMax / totalMax) * 100 : 0;

    // Generate recommendations
    const recommendations = [];
    if (percentVsNoOpt > 50) {
      recommendations.push('Excellent optimization! You are saving over 50% compared to fixed allocation.');
    } else if (percentVsNoOpt > 25) {
      recommendations.push('Good optimization. Consider tracking quality metrics to ensure performance is maintained.');
    } else if (percentVsNoOpt > 0) {
      recommendations.push('Moderate savings. Review complexity scoring to ensure optimal budget allocation.');
    } else {
      recommendations.push('Limited savings detected. Consider adjusting complexity thresholds or using adaptive allocation.');
    }

    if (costLog.length < 10) {
      recommendations.push('Collect more data (10+ calls) for more reliable savings estimates.');
    }

    // Per-call breakdown if requested
    let perCallBreakdown;
    if (includePerCall) {
      perCallBreakdown = costLog.map((e, idx) => {
        const rate = THINKING_COSTS[e.model] || THINKING_COSTS['claude-sonnet-4-6'];
        const noOptCost = (NO_OPT_TOKENS / 1000) * rate;
        return {
          callIndex: idx,
          actual: e.cost,
          noOptimization: round6(noOptCost),
          alwaysMax: e.maxCost,
          saved: round6(e.maxCost - e.cost),
          tokens: e.thinkingTokens,
          model: e.model,
          timestamp: e.timestamp,
        };
      });
    }

    return {
      actualCosts: {
        total: round6(totalActual),
        average: round6(avgActual),
        callCount: costLog.length,
      },
      noOptimizationCosts: {
        total: round6(totalNoOpt),
        average: round6(avgNoOpt),
        description: 'No optimization (typical default: 16384 tokens)',
      },
      alwaysMaxCosts: {
        total: round6(totalMax),
        average: round6(avgMax),
        description: 'Always maximum (32768 tokens)',
      },
      savings: {
        vsNoOptimization: {
          amount: round6(savingsVsNoOpt),
          percent: Math.round(percentVsNoOpt * 100) / 100,
        },
        vsAlwaysMax: {
          amount: round6(savingsVsMax),
          percent: Math.round(percentVsMax * 100) / 100,
        },
      },
      recommendations,
      perCallBreakdown: includePerCall ? perCallBreakdown : undefined,
    };
  } catch (error) {
    console.error(`Error in getComparisonReport: ${error.message}`);
    throw error;
  }
}

/**
 * P1 ENHANCEMENT: Generate a summary report with key metrics and insights.
 * Provides a quick overview of optimization performance.
 * @returns {{
 *   summary: string,
 *   metrics: {
 *     totalCalls: number,
 *     totalCost: number,
 *     avgCostPerCall: number,
 *     totalTokens: number,
 *     avgTokensPerCall: number,
 *     totalSavings: number,
 *     savingsPercent: number
 *   },
 *   insights: string[]
 * }}
 */
export function getSummaryReport() {
  try {
    if (costLog.length === 0) {
      return {
        summary: 'No tracking data available yet.',
        metrics: {
          totalCalls: 0,
          totalCost: 0,
          avgCostPerCall: 0,
          totalTokens: 0,
          avgTokensPerCall: 0,
          totalSavings: 0,
          savingsPercent: 0,
        },
        insights: ['Start using PRAXIS to track and optimize thinking token costs.'],
      };
    }

    const totalCost = costLog.reduce((sum, e) => sum + e.cost, 0);
    const totalTokens = costLog.reduce((sum, e) => sum + e.thinkingTokens, 0);
    const totalSavings = costLog.reduce((sum, e) => sum + e.saved, 0);
    const totalMaxCost = costLog.reduce((sum, e) => sum + e.maxCost, 0);

    const avgCost = totalCost / costLog.length;
    const avgTokens = totalTokens / costLog.length;
    const savingsPercent = totalMaxCost > 0 ? (totalSavings / totalMaxCost) * 100 : 0;

    // Generate insights
    const insights = [];
    insights.push(`Tracked ${costLog.length} API calls across ${new Set(costLog.map(e => e.model)).size} model(s).`);

    if (savingsPercent > 60) {
      insights.push(`Outstanding! PRAXIS saved you ${savingsPercent.toFixed(1)}% on thinking token costs.`);
    } else if (savingsPercent > 40) {
      insights.push(`Great results! You saved ${savingsPercent.toFixed(1)}% with PRAXIS optimization.`);
    } else if (savingsPercent > 20) {
      insights.push(`Good savings of ${savingsPercent.toFixed(1)}%. Consider using adaptive allocation for even better results.`);
    }

    if (avgTokens < 8192) {
      insights.push('Average token usage is efficient. Most tasks are using light to medium budgets.');
    } else if (avgTokens > 20000) {
      insights.push('High average token usage detected. Review complexity scoring if tasks seem over-allocated.');
    }

    const summary = `PRAXIS processed ${costLog.length} calls, using ${Math.round(avgTokens)} tokens on average and saving ${savingsPercent.toFixed(1)}% compared to always-max allocation.`;

    return {
      summary,
      metrics: {
        totalCalls: costLog.length,
        totalCost: round6(totalCost),
        avgCostPerCall: round6(avgCost),
        totalTokens,
        avgTokensPerCall: Math.round(avgTokens),
        totalSavings: round6(totalSavings),
        savingsPercent: Math.round(savingsPercent * 100) / 100,
      },
      insights,
    };
  } catch (error) {
    console.error(`Error in getSummaryReport: ${error.message}`);
    throw error;
  }
}

/**
 * Generate a formatted savings report for CLI display.
 * @param {Object} [options={}] - Report options.
 * @returns {string} Formatted report string.
 */
export function generateSavingsReport(options = {}) {
  try {
    const savings = getThinkingSavings();
    const log = getCostLog();

    const lines = [
      '╔══════════════════════════════════════════╗',
      '║        Praxis Savings Report             ║',
      '╠══════════════════════════════════════════╣',
      `║  Total API Calls:    ${String(savings.callCount).padStart(8).padEnd(19)}║`,
      `║  Actual Cost:        $${savings.totalActualCost.toFixed(4).padEnd(18)}║`,
      `║  Without Praxis:     $${savings.totalMaxCost.toFixed(4).padEnd(18)}║`,
      `║  Money Saved:        $${savings.totalSaved.toFixed(4).padEnd(18)}║`,
      `║  Savings Rate:       ${savings.percentSaved.toFixed(1).padStart(6)}%${' '.repeat(12)}║`,
      '╠══════════════════════════════════════════╣',
      '║  Tier Distribution:                      ║',
    ];

    // Count tier usage from log - we need to infer tier from tokens
    const tierCounts = {};
    for (const entry of log) {
      let tier = 'unknown';
      // Map tokens back to tiers
      if (entry.thinkingTokens === 0) tier = 'none';
      else if (entry.thinkingTokens <= 2048) tier = 'light';
      else if (entry.thinkingTokens <= 8192) tier = 'medium';
      else if (entry.thinkingTokens <= 16384) tier = 'heavy';
      else tier = 'max';

      tierCounts[tier] = (tierCounts[tier] || 0) + 1;
    }

    // Sort by tier order
    const tierOrder = ['none', 'light', 'medium', 'heavy', 'max', 'unknown'];
    for (const tier of tierOrder) {
      const count = tierCounts[tier] || 0;
      if (count === 0) continue;

      const pct = log.length > 0 ? ((count / log.length) * 100).toFixed(0) : '0';
      const barLength = log.length > 0 ? Math.round((count / log.length) * 20) : 0;
      const bar = '█'.repeat(barLength);
      lines.push(`║    ${tier.padEnd(10)} ${bar.padEnd(20)} ${String(pct).padStart(3)}%  ║`);
    }

    lines.push('╚══════════════════════════════════════════╝');
    return lines.join('\n');
  } catch (error) {
    console.error(`Error in generateSavingsReport: ${error.message}`);
    throw error;
  }
}

export { THINKING_COSTS, MAX_THINKING_TOKENS };
