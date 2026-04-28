/**
 * PRAXIS — recursion-tree builder tests.
 *
 * Exercises buildTree() + renderTree() against synthetic ledger rows.
 * The CXR adapter emits the right shape; here we pin the *tree
 * assembly* behaviour so future changes to the adapter can't silently
 * break the tree view.
 */

import { describe, it, expect } from '@jest/globals';
import { buildTree, renderTree } from '../lib/ledger.mjs';

/** Synthesise a joined row the way loadLedger() would produce. */
function row(sid, tid, { parent_tid = null, depth = 0, spawn_kind = 'main',
                         tier = 'heavy', effort = 'high', budget = 16384,
                         used = 9000, stop = 'end_turn' } = {}) {
  return {
    sid, tid,
    alloc: {
      sid, tid, v: 1, type: 'alloc', ts: 1700000000 + tid,
      payload: {
        parent_tid, depth, spawn_kind,
        tier, effort, budget_requested: budget,
        prompt_preview: `prompt ${tid}`, decision: 'auto_scored',
        model: 'claude-opus-4-7', model_family: 'adaptive_only',
      },
    },
    outcome: {
      sid, tid, v: 1, type: 'outcome', ts: 1700000000 + tid + 0.5,
      payload: { thinking_used: used, stop_reason: stop },
    },
  };
}

describe('buildTree', () => {
  it('returns empty forest for ledgers without CXR metadata', () => {
    const r = { sid: 's', tid: 1,
      alloc: { sid: 's', tid: 1, v: 1, type: 'alloc', ts: 1,
               payload: { tier: 'heavy' } },  // no parent_tid/depth
      outcome: null };
    const tree = buildTree([r]);
    expect(tree.size).toBe(0);
  });

  it('links a root + two children correctly', () => {
    const rows = [
      row('s', 1, { parent_tid: null, depth: 0, spawn_kind: 'main' }),
      row('s', 2, { parent_tid: 1, depth: 1, spawn_kind: 'rlm_map' }),
      row('s', 3, { parent_tid: 1, depth: 1, spawn_kind: 'rlm_map' }),
    ];
    const tree = buildTree(rows);
    const session = tree.get('s');
    expect(session.roots).toHaveLength(1);
    expect(session.roots[0].tid).toBe(1);
    expect(session.roots[0].children).toHaveLength(2);
    expect(session.roots[0].children.map((c) => c.tid).sort()).toEqual([2, 3]);
  });

  it('preserves depth + spawn_kind on every node', () => {
    const rows = [
      row('s', 1, { parent_tid: null, depth: 0, spawn_kind: 'main' }),
      row('s', 2, { parent_tid: 1, depth: 1, spawn_kind: 'rlm_map' }),
      row('s', 3, { parent_tid: 2, depth: 2, spawn_kind: 'spawn_agent' }),
    ];
    const tree = buildTree(rows);
    const root = tree.get('s').roots[0];
    expect(root.depth).toBe(0);
    expect(root.spawn_kind).toBe('main');
    const grandchild = root.children[0].children[0];
    expect(grandchild.depth).toBe(2);
    expect(grandchild.spawn_kind).toBe('spawn_agent');
  });

  it('marks orphans when parent_tid points at a missing tid', () => {
    const rows = [
      row('s', 5, { parent_tid: 99, depth: 1 }),   // parent doesn't exist
    ];
    const tree = buildTree(rows);
    const session = tree.get('s');
    expect(session.roots).toHaveLength(1);
    expect(session.roots[0].orphan).toBe(true);
  });

  it('sorts children by tid for stable rendering', () => {
    const rows = [
      row('s', 1, { parent_tid: null, depth: 0 }),
      row('s', 7, { parent_tid: 1, depth: 1 }),
      row('s', 3, { parent_tid: 1, depth: 1 }),
      row('s', 5, { parent_tid: 1, depth: 1 }),
    ];
    const tree = buildTree(rows);
    const root = tree.get('s').roots[0];
    expect(root.children.map((c) => c.tid)).toEqual([3, 5, 7]);
  });

  it('handles multiple sessions independently', () => {
    const rows = [
      row('a', 1, { depth: 0 }),
      row('b', 1, { depth: 0 }),
      row('a', 2, { parent_tid: 1, depth: 1 }),
    ];
    const tree = buildTree(rows);
    expect(tree.size).toBe(2);
    expect(tree.get('a').roots[0].children).toHaveLength(1);
    expect(tree.get('b').roots[0].children).toHaveLength(0);
  });
});

describe('renderTree', () => {
  it('includes truncation markers', () => {
    const rows = [
      row('s', 1, { depth: 0, stop: 'max_tokens' }),
    ];
    const output = renderTree(buildTree(rows));
    expect(output).toMatch(/truncated/);
  });

  it('includes orphan markers', () => {
    const rows = [
      row('s', 5, { parent_tid: 99, depth: 1 }),
    ];
    const output = renderTree(buildTree(rows));
    expect(output).toMatch(/orphan/);
  });

  it('renders non-empty ledger with branch characters', () => {
    const rows = [
      row('s', 1, { depth: 0 }),
      row('s', 2, { parent_tid: 1, depth: 1 }),
    ];
    const output = renderTree(buildTree(rows));
    expect(output).toContain('tid=1');
    expect(output).toContain('tid=2');
    expect(output).toMatch(/└─|├─/);
  });

  it('handles empty forest with a friendly message', () => {
    const output = renderTree(new Map());
    expect(output).toMatch(/nothing to render/);
  });
});
