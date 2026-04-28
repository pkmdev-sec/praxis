/**
 * PRAXIS — Ledger join + regret analysis.
 *
 * Reads the two JSONL ledgers produced by the hooks:
 *   - ``allocation-log.jsonl`` — receipts of every Praxis decision.
 *   - ``outcome-log.jsonl``    — receipts of what actually happened on each turn.
 *
 * Joins them on ``(sid, tid)``, verifies every record's HMAC (silently dropping
 * tampered rows and surfacing the count), and emits calibration-grade views:
 *
 *   loadLedger()       → { allocs, outcomes, rows, tampered }
 *   regretLedger(rows) → per-tier over/under allocation summary
 *   calibrationCurve() → score → retry rate / utilisation, used by ``bin/praxis``
 *
 * The honest story this module enables — replacing "79% saved vs always-max"
 * with "saved $X on overshoots, cost $Y on undershoots, net $Z" — is the whole
 * point of Week 1. Everything else is plumbing that serves that number.
 */

import fs from 'node:fs';
import path from 'node:path';

import { ledgerPath, verifyRecord } from './receipt.mjs';

/** Tier → canonical budget in tokens (mirrors BUDGET_TIERS in the hook). */
export const TIER_BUDGET = {
  none: 0,
  light: 2048,
  medium: 8192,
  heavy: 16384,
  max: 32768,
};

/** Score (1-10) → tier label (mirrors BUDGET_TIERS ranges). */
export function tierForScore(score) {
  const s = Math.max(1, Math.min(10, Math.round(Number(score) || 1)));
  if (s <= 2) return 'none';
  if (s <= 4) return 'light';
  if (s <= 6) return 'medium';
  if (s <= 8) return 'heavy';
  return 'max';
}

// ── Raw load ────────────────────────────────────────────────────────────────

function readJsonl(file) {
  if (!fs.existsSync(file)) return { lines: [], tampered: 0, bad: 0 };
  const content = fs.readFileSync(file, 'utf8');
  const lines = [];
  let tampered = 0;
  let bad = 0;
  for (const raw of content.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    let rec;
    try {
      rec = JSON.parse(line);
    } catch {
      bad += 1;
      continue;
    }
    if (!verifyRecord(rec)) {
      tampered += 1;
      continue;
    }
    lines.push(rec);
  }
  return { lines, tampered, bad };
}

/**
 * Load and join both ledgers.
 *
 * @param {{ home?: string }} [opts] - override PRAXIS_HOME for tests.
 * @returns {{
 *   allocs: object[],
 *   outcomes: object[],
 *   rows: Array<{ sid: string, tid: number, alloc: object, outcome: object|null }>,
 *   tampered: number,
 *   bad: number,
 * }}
 */
export function loadLedger(opts = {}) {
  const allocFile = opts.home
    ? path.join(opts.home, 'allocation-log.jsonl')
    : ledgerPath('allocation-log.jsonl');
  const outcomeFile = opts.home
    ? path.join(opts.home, 'outcome-log.jsonl')
    : ledgerPath('outcome-log.jsonl');

  const allocLoad = readJsonl(allocFile);
  const outcomeLoad = readJsonl(outcomeFile);

  // Index outcomes by (sid, tid) — one outcome per turn.
  const outcomeIndex = new Map();
  for (const o of outcomeLoad.lines) {
    outcomeIndex.set(`${o.sid}::${o.tid}`, o);
  }

  const rows = allocLoad.lines.map((a) => ({
    sid: a.sid,
    tid: a.tid,
    alloc: a,
    outcome: outcomeIndex.get(`${a.sid}::${a.tid}`) ?? null,
  }));

  return {
    allocs: allocLoad.lines,
    outcomes: outcomeLoad.lines,
    rows,
    tampered: allocLoad.tampered + outcomeLoad.tampered,
    bad: allocLoad.bad + outcomeLoad.bad,
  };
}

// ── Regret ──────────────────────────────────────────────────────────────────

/** Score mapped back from a legacy receipt whose payload is pre-v1.1. */
function extractScore(alloc) {
  const p = alloc?.payload ?? {};
  return p.complexity ?? p.complexity_score ?? null;
}

function extractTier(alloc) {
  const score = extractScore(alloc);
  return score ? tierForScore(score) : 'unknown';
}

function extractBudget(alloc) {
  const p = alloc?.payload ?? {};
  return typeof p.budget_requested === 'number'
    ? p.budget_requested
    : typeof p.tokens === 'number'
      ? p.tokens
      : null;
}

function extractThinkingUsed(outcome) {
  if (!outcome) return null;
  const p = outcome?.payload ?? {};
  return typeof p.thinking_used === 'number' ? p.thinking_used : null;
}

/**
 * Summarise per-tier and overall allocation performance.
 *
 * Definitions:
 *   - Overshoot:   thinking_used < 0.25 × budget   (paid for thinking we didn't do)
 *   - Undershoot:  stop_reason == "max_tokens" OR next turn flagged as retry
 *                  (paid too little; model ran out of runway)
 *   - Utilisation: mean thinking_used / budget, per tier
 */
export function regretLedger(rows) {
  const tiers = {};

  function bucket(label) {
    if (!tiers[label]) {
      tiers[label] = {
        tier: label,
        n: 0,
        with_outcome: 0,
        total_budget: 0,
        total_used: 0,
        overshoots: 0,
        undershoots: 0,
      };
    }
    return tiers[label];
  }

  for (const r of rows) {
    const tier = extractTier(r.alloc);
    const b = bucket(tier);
    b.n += 1;

    const budget = extractBudget(r.alloc);
    if (typeof budget === 'number') b.total_budget += budget;

    if (!r.outcome) continue;
    b.with_outcome += 1;
    const used = extractThinkingUsed(r.outcome);
    if (typeof used === 'number') {
      b.total_used += used;
      if (typeof budget === 'number' && budget > 0) {
        if (used < 0.25 * budget) b.overshoots += 1;
      }
    }

    const stop = r.outcome?.payload?.stop_reason;
    if (stop === 'max_tokens') b.undershoots += 1;
  }

  const out = Object.values(tiers)
    .map((b) => ({
      ...b,
      utilization: b.total_budget > 0 ? b.total_used / b.total_budget : null,
      overshoot_rate: b.with_outcome > 0 ? b.overshoots / b.with_outcome : null,
      undershoot_rate: b.with_outcome > 0 ? b.undershoots / b.with_outcome : null,
    }))
    .sort((x, y) => tierOrder(x.tier) - tierOrder(y.tier));

  const totals = out.reduce(
    (acc, b) => {
      acc.n += b.n;
      acc.with_outcome += b.with_outcome;
      acc.total_budget += b.total_budget;
      acc.total_used += b.total_used;
      acc.overshoots += b.overshoots;
      acc.undershoots += b.undershoots;
      return acc;
    },
    { n: 0, with_outcome: 0, total_budget: 0, total_used: 0, overshoots: 0, undershoots: 0 },
  );

  return {
    byTier: out,
    totals: {
      ...totals,
      utilization: totals.total_budget > 0 ? totals.total_used / totals.total_budget : null,
      overshoot_rate: totals.with_outcome > 0 ? totals.overshoots / totals.with_outcome : null,
      undershoot_rate: totals.with_outcome > 0 ? totals.undershoots / totals.with_outcome : null,
    },
  };
}

function tierOrder(tier) {
  const order = { none: 0, light: 1, medium: 2, heavy: 3, max: 4, unknown: 5 };
  return order[tier] ?? 99;
}

// ── Calibration curve ───────────────────────────────────────────────────────

/**
 * Per-score calibration view. For each complexity score 1-10, return the
 * empirical under-/over-allocation rates. A well-calibrated scorer should
 * produce monotonically increasing utilisation and roughly flat regret.
 */
export function calibrationCurve(rows) {
  const byScore = new Map();
  for (let s = 1; s <= 10; s += 1) {
    byScore.set(s, { score: s, n: 0, with_outcome: 0, total_budget: 0, total_used: 0, undershoots: 0 });
  }
  for (const r of rows) {
    const score = extractScore(r.alloc);
    if (!score) continue;
    const s = Math.max(1, Math.min(10, Math.round(score)));
    const b = byScore.get(s);
    b.n += 1;
    const budget = extractBudget(r.alloc);
    if (typeof budget === 'number') b.total_budget += budget;
    if (!r.outcome) continue;
    b.with_outcome += 1;
    const used = extractThinkingUsed(r.outcome);
    if (typeof used === 'number') b.total_used += used;
    if (r.outcome?.payload?.stop_reason === 'max_tokens') b.undershoots += 1;
  }
  return Array.from(byScore.values()).map((b) => ({
    ...b,
    utilization: b.total_budget > 0 ? b.total_used / b.total_budget : null,
    undershoot_rate: b.with_outcome > 0 ? b.undershoots / b.with_outcome : null,
  }));
}



// ── Recursion tree ──────────────────────────────────────────────────────────

/**
 * Build a per-session recursion tree from the joined ledger rows.
 *
 * Expects alloc payloads to carry the CXR adapter's extras
 * (`parent_tid`, `depth`, `spawn_kind`). Rows missing those
 * fields land at depth 0 with `parent_tid=null` — so pre-CXR ledgers
 * still render as flat lists rather than throwing.
 *
 * @returns {{
 *   sessions: Array<{ sid: string, roots: TreeNode[] }>,
 *   orphans: TreeNode[],
 * }}
 *
 * Each TreeNode has:
 *   { sid, tid, depth, parent_tid, kind, tier, effort, budget, used, stop, children }
 */
export function buildRecursionTree(rows) {
  const bySession = new Map();

  for (const r of rows) {
    const p = r.alloc?.payload || {};
    const out = r.outcome?.payload || {};
    const node = {
      sid: r.sid,
      tid: r.tid,
      depth: typeof p.depth === 'number' ? p.depth : 0,
      parent_tid: typeof p.parent_tid === 'number' ? p.parent_tid : null,
      kind: p.spawn_kind || null,
      tier: p.tier || null,
      effort: p.effort ?? null,
      budget: typeof p.budget_requested === 'number' ? p.budget_requested : null,
      used: typeof out.thinking_used === 'number' ? out.thinking_used : null,
      stop: out.stop_reason || null,
      escalated_from: typeof p.escalated_from === 'number' ? p.escalated_from : null,
      decision: p.decision || null,
      preview: p.prompt_preview || null,
      children: [],
    };
    if (!bySession.has(r.sid)) bySession.set(r.sid, new Map());
    bySession.get(r.sid).set(r.tid, node);
  }

  const sessions = [];
  const orphans = [];

  for (const [sid, nodes] of bySession) {
    const roots = [];
    for (const node of nodes.values()) {
      if (node.parent_tid == null) {
        roots.push(node);
      } else {
        const parent = nodes.get(node.parent_tid);
        if (parent) parent.children.push(node);
        else orphans.push(node); // parent tid not in this session's ledger
      }
    }
    // Stable order: depth-first, ascending tid among siblings.
    const sortTree = (n) => {
      n.children.sort((a, b) => a.tid - b.tid);
      n.children.forEach(sortTree);
    };
    roots.sort((a, b) => a.tid - b.tid);
    roots.forEach(sortTree);
    sessions.push({ sid, roots });
  }

  // Sessions sorted by first-root tid for stable display.
  sessions.sort((a, b) => {
    const ta = a.roots[0]?.tid ?? 0;
    const tb = b.roots[0]?.tid ?? 0;
    return ta - tb;
  });
  return { sessions, orphans };
}


// ── Recursion tree (CXR integration) ────────────────────────────────────────

/**
 * Build the per-session recursion tree from an alloc ledger that includes
 * ``parent_tid`` / ``depth`` / ``spawn_kind`` in its payload.extras.
 *
 * Walks the ``rows`` from loadLedger() and assembles a forest keyed by
 * session id. Each node references its parent tid and its direct children
 * tids; the caller can render it as a tree or flatten it as they wish.
 *
 * Returns a Map<sid, { roots: Node[], byTid: Map<tid, Node> }> where
 * ``Node`` is:
 *   {
 *     sid, tid, parent_tid, depth, spawn_kind,
 *     tier, effort, budget_requested,
 *     thinking_used, stop_reason,
 *     children: Node[],
 *   }
 *
 * Receipts without ``parent_tid`` in their extras are ignored for tree
 * construction — they're not part of a recursion tree and the report
 * command handles them separately.
 */
export function buildTree(rows) {
  const bySession = new Map();

  for (const r of rows) {
    const p = r.alloc?.payload ?? {};
    if (!('parent_tid' in p) && p.depth === undefined) {
      // Not a CXR-flavoured allocation; skip for tree building.
      continue;
    }
    if (!bySession.has(r.sid)) {
      bySession.set(r.sid, { roots: [], byTid: new Map() });
    }
    const s = bySession.get(r.sid);
    const node = {
      sid: r.sid,
      tid: r.tid,
      parent_tid: p.parent_tid ?? null,
      depth: p.depth ?? 0,
      spawn_kind: p.spawn_kind ?? 'unknown',
      tier: p.tier ?? 'unknown',
      effort: p.effort ?? null,
      budget_requested: p.budget_requested ?? null,
      thinking_used: r.outcome?.payload?.thinking_used ?? null,
      stop_reason: r.outcome?.payload?.stop_reason ?? null,
      children: [],
    };
    s.byTid.set(r.tid, node);
  }

  // Second pass: link children.
  for (const s of bySession.values()) {
    for (const node of s.byTid.values()) {
      if (node.parent_tid == null) {
        s.roots.push(node);
        continue;
      }
      const parent = s.byTid.get(node.parent_tid);
      if (parent) {
        parent.children.push(node);
      } else {
        // Orphan — parent wasn't in the ledger. Surface as a root so the
        // tree is still walkable; caller can flag the orphan.
        node.orphan = true;
        s.roots.push(node);
      }
    }
    // Stable sort children by tid so tree rendering is deterministic.
    for (const node of s.byTid.values()) {
      node.children.sort((a, b) => a.tid - b.tid);
    }
    s.roots.sort((a, b) => a.tid - b.tid);
  }

  return bySession;
}

/**
 * Render a tree as ASCII for CLI display. Follows the ``tree(1)`` convention.
 */
export function renderTree(bySession, { showUtilisation = true } = {}) {
  const lines = [];
  if (bySession.size === 0) {
    return '  (no CXR-flavoured allocations in ledger — nothing to render)\n';
  }

  for (const [sid, s] of bySession) {
    lines.push(`  session ${sid}:`);
    for (const root of s.roots) {
      renderNode(lines, root, '  ', true, showUtilisation);
    }
    lines.push('');
  }
  return lines.join('\n');
}

function renderNode(lines, node, prefix, isLast, showUtil) {
  const branch = isLast ? '└─ ' : '├─ ';
  const details = [
    `tid=${node.tid}`,
    `${node.spawn_kind}`,
    `tier=${node.tier}`,
    `effort=${node.effort ?? '-'}`,
  ];
  if (showUtil && node.thinking_used != null && node.budget_requested) {
    const util = node.thinking_used / node.budget_requested;
    details.push(`util=${(util * 100).toFixed(0)}%`);
  }
  if (node.stop_reason === 'max_tokens') details.push('⚠ truncated');
  if (node.orphan) details.push('⚠ orphan');

  lines.push(`${prefix}${branch}${details.join('  ')}`);
  const childPrefix = prefix + (isLast ? '   ' : '│  ');
  node.children.forEach((c, i) => {
    renderNode(lines, c, childPrefix, i === node.children.length - 1, showUtil);
  });
}
