import { describe, it, expect } from '@jest/globals';
import {
  EFFORT_TIERS,
  BUDGET_TIERS,
  classifyModelFamily,
  effortForScore,
  buildThinkingConfig,
  allocateForModel,
} from '../lib/effort-mapper.mjs';

describe('classifyModelFamily', () => {
  it('classifies Opus 4.7 as adaptive_only', () => {
    expect(classifyModelFamily('claude-opus-4-7')).toBe('adaptive_only');
    expect(classifyModelFamily('claude-opus-4-7-20260315')).toBe('adaptive_only');
  });

  it('classifies Mythos Preview as adaptive_only', () => {
    expect(classifyModelFamily('claude-mythos-preview')).toBe('adaptive_only');
  });

  it('classifies Opus 4.6 and Sonnet 4.6 as adaptive_preferred', () => {
    expect(classifyModelFamily('claude-opus-4-6')).toBe('adaptive_preferred');
    expect(classifyModelFamily('claude-sonnet-4-6')).toBe('adaptive_preferred');
  });

  it('classifies Opus 4.5 and earlier as manual', () => {
    expect(classifyModelFamily('claude-opus-4-5')).toBe('manual');
    expect(classifyModelFamily('claude-opus-4-1')).toBe('manual');
    expect(classifyModelFamily('claude-sonnet-4-5')).toBe('manual');
    expect(classifyModelFamily('claude-sonnet-3-7')).toBe('manual');
  });

  it('defaults unknown models to adaptive_only (future-safe)', () => {
    expect(classifyModelFamily('claude-opus-5-0')).toBe('adaptive_only');
    expect(classifyModelFamily('')).toBe('adaptive_only');
    expect(classifyModelFamily(undefined)).toBe('adaptive_only');
  });
});

describe('effortForScore', () => {
  it('maps all 10 scores to the documented effort enum', () => {
    expect(effortForScore(1)).toBe(null);
    expect(effortForScore(2)).toBe(null);
    expect(effortForScore(3)).toBe('low');
    expect(effortForScore(5)).toBe('medium');
    expect(effortForScore(7)).toBe('high');
    expect(effortForScore(9)).toBe('xhigh');
    expect(effortForScore(10)).toBe('max');
  });

  it('clamps out-of-range inputs', () => {
    expect(effortForScore(-1)).toBe(null);
    expect(effortForScore(99)).toBe('max');
    expect(effortForScore(NaN)).toBe(null);
  });
});

describe('buildThinkingConfig', () => {
  it('emits adaptive + effort only for Opus 4.7 (adaptive_only)', () => {
    const cfg = buildThinkingConfig(7, 'adaptive_only');
    expect(cfg.thinking).toEqual({ type: 'adaptive' });
    expect(cfg.output_config).toEqual({ effort: 'high' });
    expect(cfg).not.toHaveProperty('legacy_budget_tokens');
    // Critical: no budget_tokens anywhere — would be a 400 error on Opus 4.7.
    expect(cfg.thinking.budget_tokens).toBeUndefined();
  });

  it('emits empty config to skip thinking on trivial prompts (Opus 4.7)', () => {
    expect(buildThinkingConfig(1, 'adaptive_only')).toEqual({});
    expect(buildThinkingConfig(2, 'adaptive_only')).toEqual({});
  });

  it('emits adaptive + effort + legacy budget for Sonnet 4.6 (adaptive_preferred)', () => {
    const cfg = buildThinkingConfig(5, 'adaptive_preferred');
    expect(cfg.thinking).toEqual({ type: 'adaptive' });
    expect(cfg.output_config).toEqual({ effort: 'medium' });
    expect(cfg.legacy_budget_tokens).toBe(8192);
  });

  it('emits disabled thinking on adaptive_preferred when score is trivial', () => {
    expect(buildThinkingConfig(1, 'adaptive_preferred')).toEqual({
      thinking: { type: 'disabled' },
    });
  });

  it('emits manual enabled thinking for Opus 4.5 (manual family)', () => {
    const cfg = buildThinkingConfig(8, 'manual');
    expect(cfg.thinking).toEqual({ type: 'enabled', budget_tokens: 16384 });
    expect(cfg).not.toHaveProperty('output_config');
    expect(cfg).not.toHaveProperty('legacy_budget_tokens');
  });

  it('emits disabled thinking for manual when tokens would be 0', () => {
    expect(buildThinkingConfig(1, 'manual')).toEqual({
      thinking: { type: 'disabled' },
    });
  });
});

describe('allocateForModel', () => {
  it('returns a fully populated decision object', async () => {
    // Use the `ultrathink` keyword to bypass the weighted-signal scorer and
    // land in a deterministic tier. (We're asserting on the *mapper* here, not
    // the scorer; the scorer has its own tests in complexity-scorer.test.mjs.)
    const result = await allocateForModel(
      'ultrathink about a distributed system redesign',
      'claude-opus-4-7'
    );
    expect(result.complexity).toBeGreaterThanOrEqual(5);
    expect(['medium', 'high', 'xhigh', 'max']).toContain(result.effort);
    expect(result.modelFamily).toBe('adaptive_only');
    expect(result.thinkingConfig.thinking).toEqual({ type: 'adaptive' });
    expect(result.thinkingConfig.output_config.effort).toBe(result.effort);
  });

  it('picks the legacy manual shape for older models', async () => {
    const result = await allocateForModel('Fix the login bug', 'claude-opus-4-5');
    expect(result.modelFamily).toBe('manual');
    expect(result.thinkingConfig.thinking.type).toBeDefined();
    // manual shape cannot include output_config.effort.
    expect(result.thinkingConfig.output_config).toBeUndefined();
  });

  it('does not emit budget_tokens on adaptive_only models', async () => {
    const result = await allocateForModel(
      'Design a scalable distributed system',
      'claude-mythos-preview'
    );
    const tk = result.thinkingConfig.thinking || {};
    expect(tk.budget_tokens).toBeUndefined();
  });
});

describe('EFFORT_TIERS and BUDGET_TIERS parity', () => {
  it('has matching keys 1-10 in both tier maps', () => {
    for (let i = 1; i <= 10; i++) {
      expect(BUDGET_TIERS).toHaveProperty(String(i));
      expect(EFFORT_TIERS).toHaveProperty(String(i));
    }
  });

  it('null effort iff zero-token budget', () => {
    for (let i = 1; i <= 10; i++) {
      const budget = BUDGET_TIERS[i];
      const effort = EFFORT_TIERS[i];
      expect(budget === 0).toBe(effort === null);
    }
  });
});
