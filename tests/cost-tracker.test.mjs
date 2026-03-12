import { describe, it, expect, beforeEach } from '@jest/globals';
import {
  trackThinkingCost,
  getThinkingSavings,
  getThinkingEfficiency,
  getCostLog,
  resetCostLog,
  THINKING_COSTS,
  MAX_THINKING_TOKENS,
  getComparisonReport,
  getSummaryReport,
} from '../lib/cost-tracker.mjs';

beforeEach(() => {
  resetCostLog();
});

describe('trackThinkingCost', () => {
  it('calculates cost correctly for sonnet', () => {
    const result = trackThinkingCost(8192, 'claude-sonnet-4-6');
    const expected = (8192 / 1000) * THINKING_COSTS['claude-sonnet-4-6'];
    expect(result.cost).toBeCloseTo(expected, 5);
  });

  it('calculates cost correctly for opus', () => {
    const result = trackThinkingCost(8192, 'claude-opus-4-6');
    const expected = (8192 / 1000) * THINKING_COSTS['claude-opus-4-6'];
    expect(result.cost).toBeCloseTo(expected, 5);
  });

  it('calculates savings vs max budget', () => {
    const result = trackThinkingCost(2048, 'claude-sonnet-4-6');
    const maxCost = (MAX_THINKING_TOKENS / 1000) * THINKING_COSTS['claude-sonnet-4-6'];
    expect(result.maxCost).toBeCloseTo(maxCost, 5);
    expect(result.saved).toBeCloseTo(maxCost - result.cost, 5);
  });

  it('adds entry to cost log', () => {
    trackThinkingCost(1000);
    expect(getCostLog()).toHaveLength(1);
    trackThinkingCost(2000);
    expect(getCostLog()).toHaveLength(2);
  });

  it('defaults to sonnet model', () => {
    const result = trackThinkingCost(1000);
    expect(result.entry.model).toBe('claude-sonnet-4-6');
  });

  it('uses sonnet rate for unknown models', () => {
    const result = trackThinkingCost(1000, 'unknown-model');
    const expected = (1000 / 1000) * THINKING_COSTS['claude-sonnet-4-6'];
    expect(result.cost).toBeCloseTo(expected, 5);
  });
});

describe('getThinkingSavings', () => {
  it('returns zeros for empty log', () => {
    const savings = getThinkingSavings();
    expect(savings.totalActualCost).toBe(0);
    expect(savings.totalSaved).toBe(0);
    expect(savings.callCount).toBe(0);
  });

  it('calculates total savings', () => {
    trackThinkingCost(2048, 'claude-sonnet-4-6');
    trackThinkingCost(8192, 'claude-sonnet-4-6');
    const savings = getThinkingSavings();

    expect(savings.callCount).toBe(2);
    expect(savings.totalActualCost).toBeGreaterThan(0);
    expect(savings.totalMaxCost).toBeGreaterThan(savings.totalActualCost);
    expect(savings.totalSaved).toBeGreaterThan(0);
    expect(savings.percentSaved).toBeGreaterThan(0);
  });

  it('reports 0% saved when always using max', () => {
    trackThinkingCost(MAX_THINKING_TOKENS, 'claude-sonnet-4-6');
    const savings = getThinkingSavings();
    expect(savings.percentSaved).toBe(0);
  });
});

describe('getThinkingEfficiency', () => {
  it('returns zeros for empty data', () => {
    const eff = getThinkingEfficiency([]);
    expect(eff.avgQualityPerDollar).toBe(0);
    expect(eff.dataPoints).toBe(0);
  });

  it('calculates quality per dollar', () => {
    const eff = getThinkingEfficiency([
      { quality: 8, cost: 0.10 },
      { quality: 6, cost: 0.05 },
    ]);
    expect(eff.avgQualityPerDollar).toBeGreaterThan(0);
    expect(eff.dataPoints).toBe(2);
    expect(eff.bestRatio).toBeGreaterThanOrEqual(eff.worstRatio);
  });

  it('uses default quality when no data provided', () => {
    trackThinkingCost(8192, 'claude-sonnet-4-6');
    const eff = getThinkingEfficiency();
    expect(eff.dataPoints).toBe(1);
    expect(eff.avgQualityPerDollar).toBeGreaterThan(0);
  });

  it('handles zero-cost entries', () => {
    const eff = getThinkingEfficiency([
      { quality: 5, cost: 0 },
      { quality: 8, cost: 0.10 },
    ]);
    // Zero cost entries are filtered out for ratio calc
    expect(eff.dataPoints).toBe(2);
  });
});

describe('getCostLog', () => {
  it('returns a copy of the log', () => {
    trackThinkingCost(1000);
    const log = getCostLog();
    log.push({ fake: true });
    expect(getCostLog()).toHaveLength(1);
  });
});

describe('resetCostLog', () => {
  it('clears the log', () => {
    trackThinkingCost(1000);
    trackThinkingCost(2000);
    expect(getCostLog()).toHaveLength(2);
    resetCostLog();
    expect(getCostLog()).toHaveLength(0);
  });
});

// P1 ENHANCEMENT TESTS: Comparison reporting
describe('getComparisonReport', () => {

  beforeEach(() => {
    resetCostLog();
  });

  it('returns empty report for no data', () => {
    const report = getComparisonReport();
    expect(report.actualCosts.total).toBe(0);
    expect(report.actualCosts.callCount).toBe(0);
    expect(report.recommendations.length).toBeGreaterThan(0);
  });

  it('compares actual costs vs no-optimization baseline', () => {
    trackThinkingCost(2048, 'claude-sonnet-4-6');
    trackThinkingCost(8192, 'claude-sonnet-4-6');

    const report = getComparisonReport();

    expect(report.actualCosts.total).toBeGreaterThan(0);
    expect(report.noOptimizationCosts.total).toBeGreaterThan(report.actualCosts.total);
    expect(report.savings.vsNoOptimization.amount).toBeGreaterThan(0);
    expect(report.savings.vsNoOptimization.percent).toBeGreaterThan(0);
  });

  it('compares actual costs vs always-max', () => {
    trackThinkingCost(2048, 'claude-sonnet-4-6');
    trackThinkingCost(8192, 'claude-sonnet-4-6');

    const report = getComparisonReport();

    expect(report.alwaysMaxCosts.total).toBeGreaterThan(report.actualCosts.total);
    expect(report.savings.vsAlwaysMax.amount).toBeGreaterThan(0);
    expect(report.savings.vsAlwaysMax.percent).toBeGreaterThan(0);
  });

  it('provides recommendations', () => {
    trackThinkingCost(2048, 'claude-sonnet-4-6');
    const report = getComparisonReport();

    expect(Array.isArray(report.recommendations)).toBe(true);
    expect(report.recommendations.length).toBeGreaterThan(0);
  });

  it('includes per-call breakdown when requested', () => {
    trackThinkingCost(2048, 'claude-sonnet-4-6');
    trackThinkingCost(8192, 'claude-sonnet-4-6');

    const report = getComparisonReport({ includePerCall: true });

    expect(report.perCallBreakdown).toBeDefined();
    expect(Array.isArray(report.perCallBreakdown)).toBe(true);
    expect(report.perCallBreakdown.length).toBe(2);

    const call = report.perCallBreakdown[0];
    expect(call).toHaveProperty('actual');
    expect(call).toHaveProperty('noOptimization');
    expect(call).toHaveProperty('alwaysMax');
    expect(call).toHaveProperty('saved');
    expect(call).toHaveProperty('tokens');
  });

  it('excludes per-call breakdown by default', () => {
    trackThinkingCost(2048, 'claude-sonnet-4-6');
    const report = getComparisonReport();

    expect(report.perCallBreakdown).toBeUndefined();
  });

  // Edge case: single call
  it('handles single call', () => {
    trackThinkingCost(8192, 'claude-sonnet-4-6');
    const report = getComparisonReport();

    expect(report.actualCosts.callCount).toBe(1);
    expect(report.recommendations).toContain('Collect more data (10+ calls) for more reliable savings estimates.');
  });

  // Edge case: maximum token usage (no savings)
  it('handles case with no savings', () => {
    trackThinkingCost(MAX_THINKING_TOKENS, 'claude-sonnet-4-6');
    const report = getComparisonReport();

    expect(report.savings.vsAlwaysMax.amount).toBe(0);
    expect(report.savings.vsAlwaysMax.percent).toBe(0);
  });

  // Edge case: mixed models
  it('handles mixed models in cost log', () => {
    trackThinkingCost(2048, 'claude-sonnet-4-6');
    trackThinkingCost(2048, 'claude-opus-4-6');
    trackThinkingCost(2048, 'claude-haiku-4-5');

    const report = getComparisonReport();
    expect(report.actualCosts.callCount).toBe(3);
  });

  // Edge case: very efficient usage (high savings)
  it('provides appropriate recommendations for high savings', () => {
    for (let i = 0; i < 10; i++) {
      trackThinkingCost(2048, 'claude-sonnet-4-6'); // Low usage
    }
    const report = getComparisonReport();

    expect(report.savings.vsNoOptimization.percent).toBeGreaterThan(50);
    expect(report.recommendations.some(r => r.includes('Excellent') || r.includes('over 50%'))).toBe(true);
  });
});

describe('getSummaryReport', () => {

  beforeEach(() => {
    resetCostLog();
  });

  it('returns empty summary for no data', () => {
    const report = getSummaryReport();
    expect(report.summary).toContain('No tracking data');
    expect(report.metrics.totalCalls).toBe(0);
    expect(report.insights.length).toBeGreaterThan(0);
  });

  it('provides summary with key metrics', () => {
    trackThinkingCost(2048, 'claude-sonnet-4-6');
    trackThinkingCost(8192, 'claude-sonnet-4-6');
    trackThinkingCost(16384, 'claude-sonnet-4-6');

    const report = getSummaryReport();

    expect(report.summary).toBeDefined();
    expect(typeof report.summary).toBe('string');
    expect(report.metrics.totalCalls).toBe(3);
    expect(report.metrics.totalCost).toBeGreaterThan(0);
    expect(report.metrics.avgCostPerCall).toBeGreaterThan(0);
    expect(report.metrics.totalTokens).toBeGreaterThan(0);
    expect(report.metrics.avgTokensPerCall).toBeGreaterThan(0);
    expect(report.metrics.totalSavings).toBeGreaterThan(0);
    expect(report.metrics.savingsPercent).toBeGreaterThan(0);
  });

  it('provides insights based on usage patterns', () => {
    trackThinkingCost(2048, 'claude-sonnet-4-6');
    trackThinkingCost(4096, 'claude-sonnet-4-6');

    const report = getSummaryReport();

    expect(Array.isArray(report.insights)).toBe(true);
    expect(report.insights.length).toBeGreaterThan(0);
    expect(report.insights.some(i => i.includes('Tracked'))).toBe(true);
  });

  it('detects efficient usage patterns', () => {
    // Low average token usage
    for (let i = 0; i < 5; i++) {
      trackThinkingCost(2048, 'claude-sonnet-4-6');
    }

    const report = getSummaryReport();
    expect(report.insights.some(i => i.includes('efficient'))).toBe(true);
  });

  it('detects high average token usage', () => {
    // High average token usage
    for (let i = 0; i < 3; i++) {
      trackThinkingCost(28000, 'claude-sonnet-4-6');
    }

    const report = getSummaryReport();
    expect(report.insights.some(i => i.includes('High average'))).toBe(true);
  });

  // Edge case: single call
  it('handles single call', () => {
    trackThinkingCost(8192, 'claude-sonnet-4-6');
    const report = getSummaryReport();

    expect(report.metrics.totalCalls).toBe(1);
    expect(report.summary).toBeDefined();
  });

  // Edge case: excellent savings
  it('recognizes outstanding savings', () => {
    for (let i = 0; i < 10; i++) {
      trackThinkingCost(2048, 'claude-sonnet-4-6');
    }

    const report = getSummaryReport();
    expect(report.metrics.savingsPercent).toBeGreaterThan(60);
    expect(report.insights.some(i => i.includes('Outstanding') || i.includes('Great'))).toBe(true);
  });

  // Edge case: multiple models
  it('tracks usage across multiple models', () => {
    trackThinkingCost(2048, 'claude-sonnet-4-6');
    trackThinkingCost(2048, 'claude-opus-4-6');
    trackThinkingCost(2048, 'claude-haiku-4-5');

    const report = getSummaryReport();
    expect(report.insights.some(i => i.includes('3 model(s)'))).toBe(true);
  });
});

// Additional edge case tests for trackThinkingCost
describe('trackThinkingCost edge cases', () => {
  beforeEach(() => {
    resetCostLog();
  });

  it('throws error for negative tokens', () => {
    expect(() => trackThinkingCost(-100)).toThrow();
  });

  it('throws error for invalid token type', () => {
    expect(() => trackThinkingCost('invalid')).toThrow();
    expect(() => trackThinkingCost(NaN)).toThrow();
  });

  it('throws error for invalid model type', () => {
    expect(() => trackThinkingCost(1000, 123)).toThrow();
    expect(() => trackThinkingCost(1000, '')).toThrow();
  });

  it('handles zero tokens', () => {
    const result = trackThinkingCost(0, 'claude-sonnet-4-6');
    expect(result.cost).toBe(0);
    expect(result.saved).toBeGreaterThan(0);
  });

  it('handles very large token counts', () => {
    const result = trackThinkingCost(100000, 'claude-sonnet-4-6');
    expect(result.cost).toBeGreaterThan(0);
    expect(result.saved).toBeLessThan(0); // Over budget
  });
});
