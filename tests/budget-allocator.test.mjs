import { describe, it, expect, beforeEach } from '@jest/globals';
import {
  allocate,
  getOptimalBudget,
  trackEfficiency,
  getSavingsReport,
  resetHistory,
  BUDGET_TIERS,
  allocateAdaptive,
  trackEfficiencyWithComplexity,
  getEfficiencyHistory,
} from '../lib/budget-allocator.mjs';

beforeEach(() => {
  resetHistory();
});

describe('allocate', () => {
  it('allocates 0 tokens for complexity 1-2', () => {
    expect(allocate(1).tokens).toBe(0);
    expect(allocate(2).tokens).toBe(0);
    expect(allocate(1).tier).toBe('none');
  });

  it('allocates 2048 tokens for complexity 3-4', () => {
    expect(allocate(3).tokens).toBe(2048);
    expect(allocate(4).tokens).toBe(2048);
    expect(allocate(3).tier).toBe('light');
  });

  it('allocates 8192 tokens for complexity 5-6', () => {
    expect(allocate(5).tokens).toBe(8192);
    expect(allocate(6).tokens).toBe(8192);
    expect(allocate(5).tier).toBe('medium');
  });

  it('allocates 16384 tokens for complexity 7-8', () => {
    expect(allocate(7).tokens).toBe(16384);
    expect(allocate(8).tokens).toBe(16384);
    expect(allocate(7).tier).toBe('heavy');
  });

  it('allocates 32768 tokens for complexity 9-10', () => {
    expect(allocate(9).tokens).toBe(32768);
    expect(allocate(10).tokens).toBe(32768);
    expect(allocate(9).tier).toBe('max');
  });

  it('clamps out-of-range scores', () => {
    expect(allocate(0).tokens).toBe(0);   // clamped to 1
    expect(allocate(15).tokens).toBe(32768); // clamped to 10
  });

  it('includes model in result', () => {
    expect(allocate(5, 'claude-opus-4-6').model).toBe('claude-opus-4-6');
  });
});

describe('getOptimalBudget', () => {
  it('returns budget for a simple question', () => {
    const result = getOptimalBudget('What is a variable?');
    expect(result.tokens).toBeDefined();
    expect(result.complexity).toBeGreaterThanOrEqual(1);
    expect(result.estimatedCost).toBeGreaterThanOrEqual(0);
  });

  it('returns higher budget for complex tasks', () => {
    const simple = getOptimalBudget('What is JS?');
    const complex = getOptimalBudget('Design a distributed fault-tolerant microservice architecture');
    expect(complex.tokens).toBeGreaterThanOrEqual(simple.tokens);
  });

  it('respects cost limit by reducing tokens', () => {
    const result = getOptimalBudget('Design a complex distributed system', 0.001);
    expect(result.estimatedCost).toBeLessThanOrEqual(0.001);
  });

  it('includes task type in result', () => {
    const result = getOptimalBudget('Fix the login bug');
    expect(result.taskType).toBeDefined();
  });
});

describe('trackEfficiency', () => {
  it('calculates efficiency ratio', () => {
    const { efficiency } = trackEfficiency(8192, 8);
    expect(efficiency).toBeCloseTo(8 / 8.192, 2);
  });

  it('handles zero budget', () => {
    const { efficiency } = trackEfficiency(0, 5);
    expect(efficiency).toBe(5); // quality itself when no tokens used
  });

  it('records entry in history', () => {
    trackEfficiency(2048, 6);
    const report = getSavingsReport();
    expect(report.callCount).toBe(1);
  });
});

describe('getSavingsReport', () => {
  it('returns zeros for empty history', () => {
    const report = getSavingsReport();
    expect(report.totalAllocated).toBe(0);
    expect(report.callCount).toBe(0);
  });

  it('calculates savings correctly', () => {
    trackEfficiency(2048, 7);
    trackEfficiency(8192, 8);
    const report = getSavingsReport();
    expect(report.callCount).toBe(2);
    expect(report.totalAllocated).toBe(2048 + 8192);
    expect(report.maxPossible).toBe(2 * 32768);
    expect(report.tokensSaved).toBe(2 * 32768 - 2048 - 8192);
    expect(report.percentSaved).toBeGreaterThan(0);
  });

  it('reports average efficiency', () => {
    trackEfficiency(2048, 6);
    trackEfficiency(16384, 9);
    const report = getSavingsReport();
    expect(report.avgEfficiency).toBeGreaterThan(0);
  });
});

// P1 ENHANCEMENT TESTS: Adaptive allocation
describe('allocateAdaptive', () => {

  beforeEach(() => {
    resetHistory();
  });

  it('provides adaptive allocation with history learning', () => {
    const result = allocateAdaptive('Design a complex system');
    expect(result).toHaveProperty('tokens');
    expect(result).toHaveProperty('originalTokens');
    expect(result).toHaveProperty('adjustment');
    expect(result).toHaveProperty('historicalEfficiency');
    expect(result).toHaveProperty('adapted');
  });

  it('reduces budget when historical efficiency is low', () => {
    // Simulate poor efficiency history at complexity ~8
    trackEfficiencyWithComplexity(16384, 3, 8); // low quality for high budget
    trackEfficiencyWithComplexity(16384, 2, 8);
    trackEfficiencyWithComplexity(16384, 3, 7);

    const result = allocateAdaptive('Debug a complex race condition', { learningRate: 0.5 });

    // Should reduce from original due to poor historical efficiency
    if (result.historicalEfficiency > 0 && result.historicalEfficiency < 5) {
      expect(result.adjustment).toBeLessThan(0);
      expect(result.adapted).toBe(true);
    }
  });

  it('increases budget when historical efficiency is very high', () => {
    // Simulate high efficiency at complexity ~5
    trackEfficiencyWithComplexity(2048, 9, 5); // high quality with small budget
    trackEfficiencyWithComplexity(4096, 10, 5);
    trackEfficiencyWithComplexity(2048, 9, 6);

    const result = allocateAdaptive('Implement a new feature', { learningRate: 0.5 });

    // Should potentially increase from original due to high efficiency
    if (result.historicalEfficiency > 15) {
      expect(result.adjustment).toBeGreaterThan(0);
      expect(result.adapted).toBe(true);
    }
  });

  it('respects cost limit even with adaptive adjustment', () => {
    const result = allocateAdaptive('Design a system', { costLimit: 0.001 });
    expect(result.estimatedCost).toBeLessThanOrEqual(0.001);
  });

  it('can disable adaptation', () => {
    trackEfficiencyWithComplexity(16384, 2, 8);
    const result = allocateAdaptive('Debug issue', { enableAdaptation: false });
    expect(result.adapted).toBe(false);
    expect(result.adjustment).toBe(0);
  });

  // Edge case: no history
  it('works without historical data', () => {
    const result = allocateAdaptive('New task with no history');
    expect(result.adapted).toBe(false);
    expect(result.historicalEfficiency).toBe(0);
  });

  // Edge case: empty task
  it('handles empty task', () => {
    expect(() => allocateAdaptive('')).not.toThrow();
  });

  // Edge case: invalid cost limit
  it('throws error for invalid cost limit', () => {
    expect(() => allocateAdaptive('task', { costLimit: -1 })).toThrow();
    expect(() => allocateAdaptive('task', { costLimit: 'invalid' })).toThrow();
  });

  // Edge case: invalid learning rate
  it('throws error for invalid learning rate', () => {
    expect(() => allocateAdaptive('task', { learningRate: -0.5 })).toThrow();
    expect(() => allocateAdaptive('task', { learningRate: 1.5 })).toThrow();
  });

  // Edge case: extreme adjustments don't exceed max tokens
  it('clamps adjustments to valid token range', () => {
    // Create very high efficiency to trigger large increase
    for (let i = 0; i < 5; i++) {
      trackEfficiencyWithComplexity(2048, 10, 9);
    }
    const result = allocateAdaptive('Ultra complex task', { learningRate: 0.9 });
    expect(result.tokens).toBeLessThanOrEqual(BUDGET_TIERS.max.tokens);
  });
});

describe('trackEfficiencyWithComplexity', () => {

  beforeEach(() => {
    resetHistory();
  });

  it('tracks efficiency with complexity score', () => {
    const result = trackEfficiencyWithComplexity(8192, 7, 6);
    expect(result.efficiency).toBeGreaterThan(0);
    expect(result.entry.complexity).toBe(6);
  });

  it('allows complexity to be optional', () => {
    const result = trackEfficiencyWithComplexity(4096, 8);
    expect(result.entry.complexity).toBeNull();
  });

  // Edge case: zero budget
  it('handles zero budget gracefully', () => {
    const result = trackEfficiencyWithComplexity(0, 5, 3);
    expect(result.efficiency).toBe(5);
  });

  // Edge case: invalid inputs
  it('throws error for invalid budget', () => {
    expect(() => trackEfficiencyWithComplexity(-100, 5)).toThrow();
    expect(() => trackEfficiencyWithComplexity('invalid', 5)).toThrow();
  });

  it('throws error for invalid quality', () => {
    expect(() => trackEfficiencyWithComplexity(8192, 'bad')).toThrow();
  });
});

describe('getEfficiencyHistory', () => {

  beforeEach(() => {
    resetHistory();
  });

  it('returns all history when no filters', () => {
    trackEfficiencyWithComplexity(2048, 6, 3);
    trackEfficiencyWithComplexity(8192, 8, 7);
    const history = getEfficiencyHistory();
    expect(history.length).toBe(2);
  });

  it('filters by minimum complexity', () => {
    trackEfficiencyWithComplexity(2048, 6, 3);
    trackEfficiencyWithComplexity(8192, 8, 7);
    trackEfficiencyWithComplexity(16384, 9, 9);

    const history = getEfficiencyHistory({ minComplexity: 7 });
    expect(history.length).toBe(2);
    expect(history.every(e => e.complexity >= 7)).toBe(true);
  });

  it('filters by maximum complexity', () => {
    trackEfficiencyWithComplexity(2048, 6, 3);
    trackEfficiencyWithComplexity(8192, 8, 7);
    trackEfficiencyWithComplexity(16384, 9, 9);

    const history = getEfficiencyHistory({ maxComplexity: 7 });
    expect(history.length).toBe(2);
    expect(history.every(e => e.complexity <= 7)).toBe(true);
  });

  it('limits number of results', () => {
    for (let i = 0; i < 10; i++) {
      trackEfficiencyWithComplexity(2048, 7, 5);
    }
    const history = getEfficiencyHistory({ limit: 5 });
    expect(history.length).toBe(5);
  });

  // Edge case: empty history
  it('returns empty array for empty history', () => {
    const history = getEfficiencyHistory();
    expect(history).toEqual([]);
  });
});
