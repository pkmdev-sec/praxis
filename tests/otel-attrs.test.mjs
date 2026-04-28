import { describe, it, expect } from '@jest/globals';
import {
  praxisSpanAttributes,
  praxisOutcomeAttributes,
  tierAlternativeCosts,
} from '../lib/otel-attrs.mjs';

const sampleAllocation = {
  complexity: 7,
  effort: 'high',
  tokens: 16384,
  tier: 'heavy',
  model: 'claude-opus-4-7',
  modelFamily: 'adaptive_only',
  thinkingConfig: { thinking: { type: 'adaptive' }, output_config: { effort: 'high' } },
};

describe('praxisSpanAttributes', () => {
  it('emits the documented attribute keys with primitive values', () => {
    const attrs = praxisSpanAttributes(sampleAllocation, { decision: 'auto_scored' });
    expect(attrs).toMatchObject({
      'praxis.complexity_score': 7,
      'praxis.tier_chosen': 'heavy',
      'praxis.budget_requested': 16384,
      'praxis.model': 'claude-opus-4-7',
      'praxis.model_family': 'adaptive_only',
      'praxis.effort_chosen': 'high',
      'praxis.decision_mode': 'auto_scored',
    });
    // All values must be primitives (OTel can't serialise nested objects).
    for (const v of Object.values(attrs)) {
      expect(['string', 'number', 'boolean']).toContain(typeof v);
    }
  });

  it('converts null effort to empty string (OTel-safe)', () => {
    const attrs = praxisSpanAttributes({
      ...sampleAllocation, effort: null, tokens: 0, tier: 'none', complexity: 1,
    });
    expect(attrs['praxis.effort_chosen']).toBe('');
  });

  it('embeds per-tier cost estimates as JSON', () => {
    const attrs = praxisSpanAttributes(sampleAllocation);
    const costs = JSON.parse(attrs['praxis.tier_alternative_costs']);
    expect(costs).toHaveProperty('heavy');
    expect(costs.heavy).toBeGreaterThan(0);
    expect(costs.none).toBe(0);
  });

  it('throws on malformed input', () => {
    expect(() => praxisSpanAttributes(null)).toThrow(/must be an object/);
  });
});

describe('praxisOutcomeAttributes', () => {
  it('computes budget_utilization as used/requested', () => {
    const attrs = praxisOutcomeAttributes({
      reasoningTokensUsed: 8192,
      budgetRequested: 16384,
    });
    expect(attrs['praxis.reasoning_tokens_used']).toBe(8192);
    expect(attrs['praxis.budget_utilization']).toBe(0.5);
    expect(attrs['praxis.over_allocated']).toBe(0);
  });

  it('flags over_allocated when utilization is below 25% at medium+', () => {
    const attrs = praxisOutcomeAttributes({
      reasoningTokensUsed: 1000,
      budgetRequested: 16384,
    });
    expect(attrs['praxis.over_allocated']).toBe(1);
  });

  it('does not over-allocate on light tier even at low utilization', () => {
    const attrs = praxisOutcomeAttributes({
      reasoningTokensUsed: 100,
      budgetRequested: 2048,
    });
    expect(attrs['praxis.over_allocated']).toBe(0);
  });

  it('attaches quality_score when provided', () => {
    const attrs = praxisOutcomeAttributes({
      reasoningTokensUsed: 500,
      budgetRequested: 2048,
      qualityScore: 8.5,
    });
    expect(attrs['praxis.quality_score']).toBe(8.5);
  });

  it('handles zero budget gracefully', () => {
    const attrs = praxisOutcomeAttributes({
      reasoningTokensUsed: 0,
      budgetRequested: 0,
    });
    expect(attrs['praxis.budget_utilization']).toBe(0);
    expect(attrs['praxis.over_allocated']).toBe(0);
  });
});

describe('tierAlternativeCosts', () => {
  it('returns costs monotonic in tier size', () => {
    const costs = tierAlternativeCosts('claude-opus-4-7');
    expect(costs.none).toBe(0);
    expect(costs.light).toBeLessThan(costs.medium);
    expect(costs.medium).toBeLessThan(costs.heavy);
    expect(costs.heavy).toBeLessThan(costs.max);
  });

  it('falls back to Sonnet 4.6 pricing for unknown models', () => {
    const known   = tierAlternativeCosts('claude-sonnet-4-6');
    const unknown = tierAlternativeCosts('claude-made-up-model');
    expect(known).toEqual(unknown);
  });
});
