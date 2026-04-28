/**
 * PRAXIS — ledger join + regret tests.
 *
 * The join is on ``(sid, tid)`` and only accepts rows whose signature
 * verifies against the currently active key. These tests drive end-to-end
 * through the real hooks (via execFileSync) so we get coverage of the
 * allocation → outcome pairing Claude Code will actually exercise.
 */

import { describe, it, expect, beforeAll, afterAll } from '@jest/globals';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { loadLedger, regretLedger, tierForScore } from '../lib/ledger.mjs';
import { _resetKeyCache } from '../lib/receipt.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.dirname(__dirname);

const HOME = fs.mkdtempSync(path.join(os.tmpdir(), 'praxis-ledger-'));
const KEY = '1'.repeat(64);

// Inherit env so subprocess hooks use the same ledger and key.
const HOOK_ENV = { ...process.env, PRAXIS_HOME: HOME, PRAXIS_RECEIPT_KEY: KEY };

function runAllocator(prompt, sessionId, model = 'claude-sonnet-4-6') {
  const stdin = JSON.stringify({ prompt, session_id: sessionId, model });
  return execFileSync('python3', [path.join(REPO, 'hooks', 'praxis-allocator.py')], {
    input: stdin,
    encoding: 'utf8',
    env: HOOK_ENV,
  });
}

function runOutcome(payload) {
  return execFileSync('python3', [path.join(REPO, 'hooks', 'praxis-outcome.py')], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    env: HOOK_ENV,
  });
}

beforeAll(() => {
  process.env.PRAXIS_HOME = HOME;
  process.env.PRAXIS_RECEIPT_KEY = KEY;
  _resetKeyCache();
});

afterAll(() => {
  fs.rmSync(HOME, { recursive: true, force: true });
  delete process.env.PRAXIS_HOME;
  delete process.env.PRAXIS_RECEIPT_KEY;
});

describe('tierForScore', () => {
  it('maps scores to canonical tiers', () => {
    expect(tierForScore(1)).toBe('none');
    expect(tierForScore(2)).toBe('none');
    expect(tierForScore(3)).toBe('light');
    expect(tierForScore(5)).toBe('medium');
    expect(tierForScore(7)).toBe('heavy');
    expect(tierForScore(10)).toBe('max');
    expect(tierForScore(99)).toBe('max');
    expect(tierForScore(-1)).toBe('none');
  });
});

describe('ledger join — end-to-end', () => {
  it('pairs allocs and outcomes by (sid, tid)', () => {
    const sid = 'session-join-1';

    runAllocator('What is a variable?', sid);
    runOutcome({ session_id: sid, usage: { reasoning_tokens: 0 }, stop_reason: 'end_turn' });

    runAllocator('Design a distributed fault-tolerant microservice', sid);
    runOutcome({ session_id: sid, usage: { reasoning_tokens: 1200 }, stop_reason: 'end_turn' });

    runAllocator('ultrathink about this race condition', sid);
    runOutcome({ session_id: sid, usage: { reasoning_tokens: 30000 }, stop_reason: 'max_tokens' });

    const { rows, tampered, bad } = loadLedger({ home: HOME });
    expect(tampered).toBe(0);
    expect(bad).toBe(0);
    // We filter to this session because a previous test in the same file
    // may have appended rows.
    const mine = rows.filter((r) => r.sid === sid);
    expect(mine).toHaveLength(3);
    expect(mine.every((r) => r.outcome !== null)).toBe(true);
    expect(mine.map((r) => r.tid)).toEqual([1, 2, 3]);
  });

  it('produces a per-tier regret ledger with correct overshoot/undershoot counts', () => {
    const sid = 'session-regret-1';

    // Heavy tier: budget 16384. We report only 800 used → overshoot.
    runAllocator('Design a distributed system with CQRS', sid);
    runOutcome({ session_id: sid, usage: { reasoning_tokens: 800 }, stop_reason: 'end_turn' });

    // Light tier: budget 2048, no overshoot, no undershoot.
    runAllocator('fix the typo', sid);
    runOutcome({ session_id: sid, usage: { reasoning_tokens: 1900 }, stop_reason: 'end_turn' });

    // Max tier: budget 32768, stop_reason=max_tokens → undershoot.
    runAllocator('ultrathink about intermittent deadlock root cause', sid);
    runOutcome({ session_id: sid, usage: { reasoning_tokens: 32768 }, stop_reason: 'max_tokens' });

    const { rows } = loadLedger({ home: HOME });
    const mine = rows.filter((r) => r.sid === sid);
    const r = regretLedger(mine);

    const heavy = r.byTier.find((b) => b.tier === 'heavy');
    expect(heavy.overshoots).toBe(1);
    expect(heavy.undershoots).toBe(0);

    const light = r.byTier.find((b) => b.tier === 'light');
    expect(light.overshoots).toBe(0);
    expect(light.undershoots).toBe(0);

    const max = r.byTier.find((b) => b.tier === 'max');
    expect(max.undershoots).toBe(1);
  });
});

describe('ledger integrity', () => {
  it('drops tampered rows silently and surfaces the count', () => {
    const sid = 'session-tamper-1';
    runAllocator('What is a variable?', sid);
    runOutcome({ session_id: sid, usage: { reasoning_tokens: 0 }, stop_reason: 'end_turn' });

    // Tamper the outcome log by flipping the budget field in the latest row.
    const file = path.join(HOME, 'outcome-log.jsonl');
    const lines = fs.readFileSync(file, 'utf8').trim().split('\n');
    const last = JSON.parse(lines[lines.length - 1]);
    last.payload.thinking_used = 99999;
    lines[lines.length - 1] = JSON.stringify(last);
    fs.writeFileSync(file, lines.join('\n') + '\n');

    const { tampered } = loadLedger({ home: HOME });
    expect(tampered).toBeGreaterThanOrEqual(1);
  });
});
