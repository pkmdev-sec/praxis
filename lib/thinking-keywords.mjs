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

/**
 * P1 ENHANCEMENT: Automatically inject thinking keyword based on complexity score.
 * Integrates with complexity scorer to determine optimal keyword and inject it if needed.
 * @param {string} prompt - The original prompt.
 * @param {number} complexityScore - Complexity score from 1-10.
 * @param {object} [options] - Options for injection.
 * @param {boolean} [options.forceInject=false] - Inject even if one exists at same level.
 * @param {boolean} [options.upgrade=true] - Upgrade existing keyword if complexity warrants it.
 * @returns {{
 *   modified: boolean,
 *   prompt: string,
 *   injectedKeyword: string|null,
 *   existingKeyword: string|null,
 *   suggestedLevel: string|null,
 *   reason: string
 * }}
 */
export function autoInjectByComplexity(prompt, complexityScore, options = {}) {
  try {
    const { forceInject = false, upgrade = true } = options;

    // Input validation
    if (prompt === null || prompt === undefined) {
      return {
        modified: false,
        prompt: '',
        injectedKeyword: null,
        existingKeyword: null,
        suggestedLevel: null,
        reason: 'Empty prompt',
      };
    }
    if (typeof prompt !== 'string') {
      throw new Error(`Invalid prompt: expected string, got ${typeof prompt}`);
    }
    if (typeof complexityScore !== 'number' || isNaN(complexityScore)) {
      throw new Error(`Invalid complexityScore: expected number, got ${typeof complexityScore}`);
    }

    if (prompt.trim() === '') {
      return {
        modified: false,
        prompt,
        injectedKeyword: null,
        existingKeyword: null,
        suggestedLevel: null,
        reason: 'Empty prompt',
      };
    }

    // Get suggestion based on complexity
    const suggestion = suggestLevel(complexityScore);

    // If no keyword suggested, don't inject
    if (!suggestion.keyword) {
      return {
        modified: false,
        prompt,
        injectedKeyword: null,
        existingKeyword: null,
        suggestedLevel: null,
        reason: suggestion.reason,
      };
    }

    // Check existing keyword
    const existing = detectThinkingLevel(prompt);

    // If no existing keyword, inject
    if (!existing.keyword) {
      const result = injectKeyword(prompt, suggestion.level);
      return {
        modified: result.modified,
        prompt: result.prompt,
        injectedKeyword: result.injectedKeyword,
        existingKeyword: null,
        suggestedLevel: suggestion.level,
        reason: `Injected '${result.injectedKeyword}' for complexity ${complexityScore}`,
      };
    }

    // Existing keyword found
    const existingTokens = KEYWORD_MAP[existing.keyword].tokens;
    const suggestedTokens = KEYWORD_MAP[suggestion.keyword].tokens;

    // If existing is sufficient or better
    if (existingTokens >= suggestedTokens && !forceInject) {
      return {
        modified: false,
        prompt,
        injectedKeyword: null,
        existingKeyword: existing.keyword,
        suggestedLevel: suggestion.level,
        reason: `Existing '${existing.keyword}' is sufficient for complexity ${complexityScore}`,
      };
    }

    // Upgrade if enabled
    if (upgrade && existingTokens < suggestedTokens) {
      const result = injectKeyword(prompt, suggestion.level);
      return {
        modified: result.modified,
        prompt: result.prompt,
        injectedKeyword: result.injectedKeyword,
        existingKeyword: existing.keyword,
        suggestedLevel: suggestion.level,
        reason: `Upgraded from '${existing.keyword}' to '${result.injectedKeyword}' for complexity ${complexityScore}`,
      };
    }

    return {
      modified: false,
      prompt,
      injectedKeyword: null,
      existingKeyword: existing.keyword,
      suggestedLevel: suggestion.level,
      reason: `Keeping existing '${existing.keyword}'`,
    };
  } catch (error) {
    console.error(`Error in autoInjectByComplexity: ${error.message}`);
    throw error;
  }
}

/**
 * P1 ENHANCEMENT: Batch process multiple prompts with automatic keyword injection.
 * Useful for preprocessing a batch of tasks with optimal thinking keywords.
 * @param {string[]} prompts - Array of prompts to process.
 * @param {(prompt: string) => number} [complexityScorer] - Optional custom complexity scorer function.
 * @returns {{
 *   results: Array<{ original: string, modified: string, keyword: string|null, complexity: number }>,
 *   stats: { totalProcessed: number, totalModified: number, keywordCounts: object }
 * }}
 */
export function batchAutoInject(prompts, complexityScorer) {
  try {
    // Input validation
    if (!Array.isArray(prompts)) {
      throw new Error(`Invalid prompts: expected array, got ${typeof prompts}`);
    }
    if (complexityScorer && typeof complexityScorer !== 'function') {
      throw new Error(`Invalid complexityScorer: expected function, got ${typeof complexityScorer}`);
    }

    // Default scorer if not provided
    const scorer = complexityScorer || ((p) => {
      // Simple heuristic: based on word count
      const words = p.trim().split(/\s+/).length;
      if (words <= 10) return 2;
      if (words <= 30) return 4;
      if (words <= 80) return 6;
      if (words <= 150) return 8;
      return 10;
    });

    const results = [];
    const keywordCounts = { think: 0, megathink: 0, ultrathink: 0, none: 0 };

    for (const prompt of prompts) {
      if (typeof prompt !== 'string') {
        results.push({
          original: prompt,
          modified: prompt,
          keyword: null,
          complexity: 0,
          error: 'Invalid prompt type',
        });
        continue;
      }

      const complexity = scorer(prompt);
      const result = autoInjectByComplexity(prompt, complexity);

      results.push({
        original: prompt,
        modified: result.prompt,
        keyword: result.injectedKeyword || result.existingKeyword,
        complexity,
      });

      if (result.injectedKeyword) {
        keywordCounts[result.injectedKeyword]++;
      } else if (result.existingKeyword) {
        keywordCounts[result.existingKeyword]++;
      } else {
        keywordCounts.none++;
      }
    }

    return {
      results,
      stats: {
        totalProcessed: prompts.length,
        totalModified: results.filter(r => r.modified !== r.original).length,
        keywordCounts,
      },
    };
  } catch (error) {
    console.error(`Error in batchAutoInject: ${error.message}`);
    throw error;
  }
}

export { KEYWORD_MAP, COMPLEXITY_KEYWORDS };
