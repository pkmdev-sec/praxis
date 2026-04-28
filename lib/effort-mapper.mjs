/**
 * PRAXIS — Effort Mapper
 *
 * Maps complexity scores to Anthropic's `effort` enum and selects the correct
 * thinking-API shape for a given model family. Mirrors
 * `hooks/praxis-allocator.py::build_thinking_config` so the JS SDK and the
 * Claude Code hook stay in lockstep.
 *
 * Model family contracts (sources: Anthropic docs, April 2026):
 *   - adaptive_only     : Opus 4.7, Mythos Preview. Only `thinking:{type:"adaptive"}`
 *                         + `effort` is accepted. Manual `budget_tokens` → 400.
 *   - adaptive_preferred: Opus 4.6, Sonnet 4.6. `effort` recommended;
 *                         `budget_tokens` still accepted but deprecated.
 *   - manual            : Opus 4.5 and earlier. Only
 *                         `thinking:{type:"enabled", budget_tokens:N}`.
 */

// Anthropic effort enum per https://docs.anthropic.com/en/docs/build-with-claude/effort.
// `null` means "skip thinking entirely" (score 1-2).
export const EFFORT_TIERS = {
  1: null, 2: null,
  3: 'low', 4: 'low',
  5: 'medium', 6: 'medium',
  7: 'high', 8: 'high',
  9: 'xhigh', 10: 'max',
};

export const BUDGET_TIERS = {
  1: 0, 2: 0,
  3: 2048, 4: 2048,
  5: 8192, 6: 8192,
  7: 16384, 8: 16384,
  9: 32768, 10: 32768,
};

// Order matters: most specific patterns first.
const MODEL_FAMILY_PATTERNS = [
  [/^claude-mythos/i,        'adaptive_only'],
  [/^claude-opus-4-7/i,      'adaptive_only'],
  [/^claude-opus-4-6/i,      'adaptive_preferred'],
  [/^claude-sonnet-4-6/i,    'adaptive_preferred'],
  [/^claude-haiku-4-5/i,     'manual'],
  [/^claude-(opus-4-5|opus-4-1|opus-4\b|sonnet-4-5|sonnet-4\b|haiku-4|sonnet-3-7)/i, 'manual'],
];

/**
 * Classify a model name into one of {adaptive_only, adaptive_preferred, manual}.
 * Unknown models default to `adaptive_only` — safer than emitting deprecated
 * fields to a future model that might reject them.
 * @param {string} model
 * @returns {'adaptive_only'|'adaptive_preferred'|'manual'}
 */
export function classifyModelFamily(model) {
  if (typeof model !== 'string' || model.trim() === '') {
    return 'adaptive_only';
  }
  for (const [pattern, family] of MODEL_FAMILY_PATTERNS) {
    if (pattern.test(model)) return family;
  }
  return 'adaptive_only';
}

/**
 * Resolve a complexity score into an effort level.
 * @param {number} complexity 1-10
 * @returns {'low'|'medium'|'high'|'xhigh'|'max'|null}
 */
export function effortForScore(complexity) {
  const clamped = Math.max(1, Math.min(10, Math.round(Number(complexity) || 1)));
  return EFFORT_TIERS[clamped] ?? null;
}

/**
 * Build the provider-specific thinking config for a given complexity score and
 * model family. Returned object maps directly to Anthropic request fields.
 *
 * Returns an empty object (`{}`) when thinking should be skipped on
 * `adaptive_only` models — the caller should simply not include a thinking key
 * in the outgoing request.
 *
 * @param {number} complexity 1-10
 * @param {'adaptive_only'|'adaptive_preferred'|'manual'} family
 * @returns {object}
 */
export function buildThinkingConfig(complexity, family) {
  const clamped = Math.max(1, Math.min(10, Math.round(Number(complexity) || 1)));
  const effort = EFFORT_TIERS[clamped] ?? null;
  const tokens = BUDGET_TIERS[clamped] ?? 8192;

  if (family === 'adaptive_only') {
    if (effort === null) return {};
    return {
      thinking: { type: 'adaptive' },
      output_config: { effort },
    };
  }

  if (family === 'adaptive_preferred') {
    if (effort === null) {
      return { thinking: { type: 'disabled' } };
    }
    return {
      thinking: { type: 'adaptive' },
      output_config: { effort },
      legacy_budget_tokens: tokens,
    };
  }

  // manual (Opus 4.5 and earlier)
  if (tokens === 0) {
    return { thinking: { type: 'disabled' } };
  }
  return { thinking: { type: 'enabled', budget_tokens: tokens } };
}

/**
 * Convenience: given (task, model), run the complexity scorer and produce the
 * full allocation decision plus thinking config. Designed for direct use in
 * integrations (LiteLLM pre-call, LangGraph node hook, etc.).
 *
 * @param {string} task
 * @param {string} [model='claude-sonnet-4-6']
 * @returns {{
 *   complexity: number,
 *   effort: string|null,
 *   tokens: number,
 *   tier: string,
 *   model: string,
 *   modelFamily: string,
 *   thinkingConfig: object,
 * }}
 */
export async function allocateForModel(task, model = 'claude-sonnet-4-6') {
  // Lazy import to avoid a circular dep with budget-allocator.mjs.
  const { scoreComplexity } = await import('./complexity-scorer.mjs');
  const { allocate } = await import('./budget-allocator.mjs');
  const complexity = scoreComplexity(task || '');
  const { tokens, tier } = allocate(complexity, model);
  const family = classifyModelFamily(model);
  const effort = effortForScore(complexity);
  const thinkingConfig = buildThinkingConfig(complexity, family);
  return {
    complexity,
    effort,
    tokens,
    tier,
    model,
    modelFamily: family,
    thinkingConfig,
  };
}
