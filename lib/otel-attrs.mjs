/**
 * PRAXIS — OpenTelemetry / OpenInference span attributes.
 *
 * Emits Praxis-specific attributes alongside the OpenInference semantic
 * conventions (https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md)
 * so dashboards in Phoenix, Langfuse, OpenLLMetry, and any OTel collector can
 * plot "budget chosen vs reasoning tokens actually used vs quality" out of the box.
 *
 * Attribute naming pattern mirrors `llm.token_count.completion_details.reasoning`
 * so Praxis decisions sit naturally next to the standard reasoning telemetry.
 *
 *   praxis.complexity_score       -> float 1-10
 *   praxis.tier_chosen            -> "none"|"light"|"medium"|"heavy"|"max"
 *   praxis.effort_chosen          -> null|"low"|"medium"|"high"|"xhigh"|"max"
 *   praxis.model_family           -> "adaptive_only"|"adaptive_preferred"|"manual"
 *   praxis.budget_requested       -> integer tokens (0 when effort-only)
 *   praxis.decision_mode          -> "auto_scored"|"keyword_override"
 *   praxis.tier_alternative_costs -> JSON string with per-tier USD estimates
 *
 * Usage:
 *
 *   import { praxisSpanAttributes } from "@praxis/lib/otel-attrs.mjs";
 *   const attrs = praxisSpanAttributes(allocation, { model, decision });
 *   span.setAttributes(attrs);            // @opentelemetry/api
 *
 * All functions return plain {string: primitive} maps so they work with any
 * OTel SDK, LangSmith run tags, or Langfuse's `metadata` field.
 */

// Per-thousand USD cost for thinking tokens on current Claude models.
// Mirrors lib/budget-allocator.mjs::MODEL_COSTS; duplicated here to avoid a
// circular import at span-emission time.
const THINKING_COST_PER_1K = {
  'claude-opus-4-7':   0.06,
  'claude-opus-4-6':   0.06,
  'claude-opus-4-5':   0.06,
  'claude-sonnet-4-6': 0.012,
  'claude-haiku-4-5':  0.003,
};

const TIER_TOKENS = {
  none:   0,
  light:  2048,
  medium: 8192,
  heavy:  16384,
  max:    32768,
};

/**
 * Compute per-tier USD cost estimates for the given model.
 * @param {string} model
 * @returns {{[tier:string]: number}}
 */
export function tierAlternativeCosts(model = 'claude-sonnet-4-6') {
  const per1k = THINKING_COST_PER_1K[model] ?? THINKING_COST_PER_1K['claude-sonnet-4-6'];
  const out = {};
  for (const [tier, tokens] of Object.entries(TIER_TOKENS)) {
    out[tier] = Math.round((tokens / 1000) * per1k * 1e6) / 1e6;
  }
  return out;
}

/**
 * Build the attribute map for a single Praxis decision.
 *
 * @param {object} allocation   Shape returned by allocateForModel():
 *   { complexity, effort, tokens, tier, model, modelFamily, thinkingConfig }
 * @param {object} [extra]      Optional { decision: "auto_scored"|"keyword_override" }
 * @returns {{[key:string]: string|number}}
 */
export function praxisSpanAttributes(allocation, extra = {}) {
  if (!allocation || typeof allocation !== 'object') {
    throw new TypeError('allocation must be an object from allocateForModel()');
  }

  const {
    complexity,
    effort = null,
    tokens = 0,
    tier = 'none',
    model = 'claude-sonnet-4-6',
    modelFamily = 'adaptive_only',
  } = allocation;

  const attrs = {
    'praxis.complexity_score': Number(complexity),
    'praxis.tier_chosen': tier,
    'praxis.budget_requested': Number(tokens),
    'praxis.model': model,
    'praxis.model_family': modelFamily,
    // OTel forbids `null` attribute values. Use the empty string to
    // represent "thinking skipped" (matches Anthropic's "omit thinking field").
    'praxis.effort_chosen': effort ?? '',
    'praxis.tier_alternative_costs': JSON.stringify(tierAlternativeCosts(model)),
  };

  if (extra.decision) {
    attrs['praxis.decision_mode'] = String(extra.decision);
  }

  return attrs;
}

/**
 * Compute post-call attributes after the Claude response returns. These sit
 * alongside the standard OpenInference `llm.token_count.*` attributes and are
 * the signal the feedback loop trains on.
 *
 * @param {object} params
 * @param {number} params.reasoningTokensUsed  Actual thinking tokens consumed
 *   (read from Claude's response usage or OTel
 *   `llm.token_count.completion_details.reasoning`).
 * @param {number} params.budgetRequested       Tokens Praxis originally requested.
 * @param {number} [params.qualityScore]        Optional 0-10 LLM-as-judge score.
 * @returns {{[key:string]: number}}
 */
export function praxisOutcomeAttributes({
  reasoningTokensUsed,
  budgetRequested,
  qualityScore,
} = {}) {
  const used = Math.max(0, Number(reasoningTokensUsed) || 0);
  const req  = Math.max(0, Number(budgetRequested)   || 0);
  const utilization = req > 0 ? Math.round((used / req) * 1000) / 1000 : 0;

  const attrs = {
    'praxis.reasoning_tokens_used': used,
    'praxis.budget_utilization': utilization,
    // Utilization ≤ 0.25 on a ≥ medium tier means Praxis likely over-allocated.
    'praxis.over_allocated': req >= TIER_TOKENS.medium && utilization < 0.25 ? 1 : 0,
  };

  if (typeof qualityScore === 'number' && !Number.isNaN(qualityScore)) {
    attrs['praxis.quality_score'] = qualityScore;
  }

  return attrs;
}
