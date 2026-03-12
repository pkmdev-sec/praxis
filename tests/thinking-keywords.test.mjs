import { describe, it, expect } from '@jest/globals';
import {
  detectThinkingLevel,
  suggestLevel,
  injectKeyword,
  getKeywordMap,
} from '../lib/thinking-keywords.mjs';

describe('detectThinkingLevel', () => {
  it('detects "think" keyword', () => {
    const result = detectThinkingLevel('think about how to optimize this');
    expect(result.keyword).toBe('think');
    expect(result.level).toBe('standard');
    expect(result.tokens).toBe(8192);
  });

  it('detects "megathink" keyword', () => {
    const result = detectThinkingLevel('megathink through this architecture');
    expect(result.keyword).toBe('megathink');
    expect(result.level).toBe('deep');
    expect(result.tokens).toBe(16384);
  });

  it('detects "ultrathink" keyword', () => {
    const result = detectThinkingLevel('ultrathink about this complex problem');
    expect(result.keyword).toBe('ultrathink');
    expect(result.level).toBe('maximum');
    expect(result.tokens).toBe(32768);
  });

  it('returns highest level when multiple keywords present', () => {
    // ultrathink is checked first, so it wins
    const result = detectThinkingLevel('ultrathink and think about this');
    expect(result.keyword).toBe('ultrathink');
  });

  it('returns null for no keywords', () => {
    const result = detectThinkingLevel('Fix the login bug');
    expect(result.keyword).toBeNull();
    expect(result.tokens).toBe(0);
  });

  it('handles empty input', () => {
    expect(detectThinkingLevel('').keyword).toBeNull();
    expect(detectThinkingLevel(null).keyword).toBeNull();
  });

  it('is case insensitive', () => {
    expect(detectThinkingLevel('MEGATHINK about this').keyword).toBe('megathink');
    expect(detectThinkingLevel('UltraThink deeply').keyword).toBe('ultrathink');
  });
});

describe('suggestLevel', () => {
  it('suggests no keyword for low complexity', () => {
    expect(suggestLevel(1).keyword).toBeNull();
    expect(suggestLevel(2).keyword).toBeNull();
  });

  it('suggests "think" for moderate complexity', () => {
    expect(suggestLevel(3).keyword).toBe('think');
    expect(suggestLevel(5).keyword).toBe('think');
    expect(suggestLevel(6).keyword).toBe('think');
  });

  it('suggests "megathink" for high complexity', () => {
    expect(suggestLevel(7).keyword).toBe('megathink');
    expect(suggestLevel(8).keyword).toBe('megathink');
  });

  it('suggests "ultrathink" for max complexity', () => {
    expect(suggestLevel(9).keyword).toBe('ultrathink');
    expect(suggestLevel(10).keyword).toBe('ultrathink');
  });

  it('includes a reason', () => {
    const result = suggestLevel(7);
    expect(result.reason).toContain('Complexity 7');
  });

  it('clamps out-of-range values', () => {
    expect(suggestLevel(0).keyword).toBeNull();
    expect(suggestLevel(15).keyword).toBe('ultrathink');
  });
});

describe('injectKeyword', () => {
  it('injects keyword at the beginning', () => {
    const result = injectKeyword('solve this problem', 'deep');
    expect(result.modified).toBe(true);
    expect(result.prompt).toBe('megathink solve this problem');
    expect(result.injectedKeyword).toBe('megathink');
  });

  it('does not downgrade existing keyword', () => {
    const result = injectKeyword('ultrathink solve this problem', 'standard');
    expect(result.modified).toBe(false);
    expect(result.prompt).toBe('ultrathink solve this problem');
  });

  it('upgrades existing keyword', () => {
    const result = injectKeyword('think solve this problem', 'maximum');
    expect(result.modified).toBe(true);
    expect(result.prompt).toContain('ultrathink');
    expect(result.prompt).not.toMatch(/\bthink\b.*ultrathink/);
  });

  it('handles invalid level gracefully', () => {
    const result = injectKeyword('test prompt', 'invalid');
    expect(result.modified).toBe(false);
  });

  it('handles empty prompt', () => {
    const result = injectKeyword('', 'standard');
    expect(result.modified).toBe(false);
  });
});

describe('getKeywordMap', () => {
  it('returns all three keywords', () => {
    const map = getKeywordMap();
    expect(map).toHaveProperty('think');
    expect(map).toHaveProperty('megathink');
    expect(map).toHaveProperty('ultrathink');
  });

  it('each entry has tokens, level, description', () => {
    const map = getKeywordMap();
    for (const entry of Object.values(map)) {
      expect(entry).toHaveProperty('tokens');
      expect(entry).toHaveProperty('level');
      expect(entry).toHaveProperty('description');
      expect(typeof entry.tokens).toBe('number');
    }
  });

  it('returns a copy, not the original', () => {
    const map1 = getKeywordMap();
    map1.newKey = 'test';
    const map2 = getKeywordMap();
    expect(map2).not.toHaveProperty('newKey');
  });
});
