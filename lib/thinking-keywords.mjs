/**
 * PRAXIS — Thinking Keywords
 * Manages thinking trigger keywords and their token budget mappings.
 */

// Keyword-to-token-budget mapping
const KEYWORD_MAP = {
  think:      { tokens: 8192,  level: 'standard', description: 'Standard extended thinking' },
  megathink:  { tokens: 16384, level: 'deep',     description: 'Deep reasoning for complex tasks' },
  ultrathink: { tokens: 32768, level: 'maximum',  description: 'Maximum reasoning for hardest tasks' },
};

// Complexity-to-keyword mapping
const COMPLEXITY_KEYWORDS = {
  1:  null,          // No thinking keyword needed
  2:  null,
  3:  'think',
  4:  'think',
  5:  'think',
  6:  'think',
  7:  'megathink',
  8:  'megathink',
  9:  'ultrathink',
  10: 'ultrathink',
};

// Patterns to detect existing thinking keywords in prompts
const KEYWORD_PATTERNS = [
  { keyword: 'ultrathink', pattern: /\bultrathink\b/i },
  { keyword: 'megathink',  pattern: /\bmegathink\b/i },
  { keyword: 'think',      pattern: /\bthink\b/i },
];

/**
 * Detect the thinking level from a prompt by scanning for keywords.
 * Returns the highest-level keyword found.
 * @param {string} prompt - The user prompt.
 * @returns {{ keyword: string|null, level: string|null, tokens: number }}
 */
export function detectThinkingLevel(prompt) {
  if (!prompt || typeof prompt !== 'string') {
    return { keyword: null, level: null, tokens: 0 };
  }

  // Check from highest to lowest priority
  for (const { keyword, pattern } of KEYWORD_PATTERNS) {
    if (pattern.test(prompt)) {
      const entry = KEYWORD_MAP[keyword];
      return {
        keyword,
        level: entry.level,
        tokens: entry.tokens,
      };
    }
  }

  return { keyword: null, level: null, tokens: 0 };
}

/**
 * Suggest the appropriate thinking level for a given complexity score.
 * @param {number} complexity - Complexity score 1-10.
 * @returns {{ keyword: string|null, level: string|null, tokens: number, reason: string }}
 */
export function suggestLevel(complexity) {
  const score = Math.max(1, Math.min(10, Math.round(complexity)));
  const keyword = COMPLEXITY_KEYWORDS[score];

  if (!keyword) {
    return {
      keyword: null,
      level: null,
      tokens: 0,
      reason: `Complexity ${score} is low enough to skip extended thinking`,
    };
  }

  const entry = KEYWORD_MAP[keyword];
  return {
    keyword,
    level: entry.level,
    tokens: entry.tokens,
    reason: `Complexity ${score} benefits from ${entry.description.toLowerCase()}`,
  };
}

/**
 * Inject a thinking keyword into a prompt if it would be beneficial.
 * Does not inject if the prompt already contains a thinking keyword at
 * the same or higher level.
 * @param {string} prompt - The original prompt.
 * @param {string} level - Target level: 'standard', 'deep', or 'maximum'.
 * @returns {{ modified: boolean, prompt: string, injectedKeyword: string|null }}
 */
export function injectKeyword(prompt, level) {
  if (!prompt || typeof prompt !== 'string') {
    return { modified: false, prompt: prompt || '', injectedKeyword: null };
  }

  // Map level to keyword
  const levelToKeyword = {
    standard: 'think',
    deep: 'megathink',
    maximum: 'ultrathink',
  };

  const targetKeyword = levelToKeyword[level];
  if (!targetKeyword) {
    return { modified: false, prompt, injectedKeyword: null };
  }

  // Check if prompt already has a thinking keyword
  const existing = detectThinkingLevel(prompt);
  if (existing.keyword) {
    const existingTokens = KEYWORD_MAP[existing.keyword].tokens;
    const targetTokens = KEYWORD_MAP[targetKeyword].tokens;

    // Don't downgrade existing keyword
    if (existingTokens >= targetTokens) {
      return { modified: false, prompt, injectedKeyword: null };
    }

    // Upgrade: replace existing keyword with target
    const existingPattern = KEYWORD_PATTERNS.find(p => p.keyword === existing.keyword).pattern;
    const upgraded = prompt.replace(existingPattern, targetKeyword);
    return { modified: true, prompt: upgraded, injectedKeyword: targetKeyword };
  }

  // Inject keyword at the beginning of the prompt
  const injected = `${targetKeyword} ${prompt}`;
  return { modified: true, prompt: injected, injectedKeyword: targetKeyword };
}

/**
 * Return the full keyword-to-token-budget mapping.
 * @returns {Record<string, { tokens: number, level: string, description: string }>}
 */
export function getKeywordMap() {
  return { ...KEYWORD_MAP };
}

export { KEYWORD_MAP, COMPLEXITY_KEYWORDS };
