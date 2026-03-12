import { describe, it, expect, beforeEach } from '@jest/globals';
import {
  allocate,
  getOptimalBudget,
  trackEfficiency,
  getSavingsReport,
  resetHistory,
  BUDGET_TIERS,
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
