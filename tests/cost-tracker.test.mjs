import { describe, it, expect, beforeEach } from '@jest/globals';
import {
  trackThinkingCost,
  getThinkingSavings,
  getThinkingEfficiency,
  getCostLog,
  resetCostLog,
  THINKING_COSTS,
  MAX_THINKING_TOKENS,
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
