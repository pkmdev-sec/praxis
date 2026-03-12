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
// Fix: use more specific patterns to avoid false positives with natural language
const KEYWORD_PATTERNS = [
  { keyword: 'ultrathink', pattern: /\bultrathink\b/i },
  { keyword: 'megathink',  pattern: /\bmegathink\b/i },
  // More specific pattern for 'think' to reduce false positives:
  // - Matches at start of string: "think about..." (user instruction)
  // - Matches with directive words: "think step by step", "think carefully", etc.
  // - Does NOT match mid-sentence conversational use: "I need to think about this"
  { keyword: 'think',      pattern: /(?:^\s*think\s+(?:about|through|of|on|over|hard(?:er)?)\b)|(?:\bthink\s+(?:step\s+by\s+step|carefully|deeply|critically|systematically|logically)\b)/i },
];

/**
 * Detect the thinking level from a prompt by scanning for keywords.
 * Returns the highest-level keyword found.
 * @param {string} prompt - The user prompt.
 * @returns {{ keyword: string|null, level: string|null, tokens: number }}
 */
export function detectThinkingLevel(prompt) {
  try {
    // Input validation
    if (prompt === null || prompt === undefined) {
      return { keyword: null, level: null, tokens: 0 };
    }
    if (typeof prompt !== 'string') {
      throw new Error(`Invalid prompt: expected string, got ${typeof prompt}`);
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
  } catch (error) {
    console.error(`Error in detectThinkingLevel: ${error.message}`);
    throw error;
  }
}

/**
 * Suggest the appropriate thinking level for a given complexity score.
 * @param {number} complexity - Complexity score 1-10.
 * @returns {{ keyword: string|null, level: string|null, tokens: number, reason: string }}
 */
export function suggestLevel(complexity) {
  try {
    // Input validation
    if (typeof complexity !== 'number' || isNaN(complexity)) {
      throw new Error(`Invalid complexity: expected number, got ${typeof complexity}`);
    }

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
  } catch (error) {
    console.error(`Error in suggestLevel: ${error.message}`);
    throw error;
  }
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
  try {
    // Input validation
    if (prompt === null || prompt === undefined) {
      return { modified: false, prompt: '', injectedKeyword: null };
    }
    if (typeof prompt !== 'string') {
      throw new Error(`Invalid prompt: expected string, got ${typeof prompt}`);
    }
    if (typeof level !== 'string') {
      throw new Error(`Invalid level: expected string, got ${typeof level}`);
    }

    // Don't inject into empty prompts
    if (prompt.trim() === '') {
      return { modified: false, prompt, injectedKeyword: null };
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
  } catch (error) {
    console.error(`Error in injectKeyword: ${error.message}`);
    throw error;
  }
}

/**
 * Return the full keyword-to-token-budget mapping.
 * @returns {Record<string, { tokens: number, level: string, description: string }>}
 */
export function getKeywordMap() {
  try {
    return { ...KEYWORD_MAP };
  } catch (error) {
    console.error(`Error in getKeywordMap: ${error.message}`);
    throw error;
  }
}

export { KEYWORD_MAP, COMPLEXITY_KEYWORDS };
