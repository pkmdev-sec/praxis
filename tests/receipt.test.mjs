/**
 * PRAXIS — receipt signing / verification tests.
 *
 * Two properties matter:
 *   1. A Python-signed record must verify from JS, and vice-versa.
 *   2. Any mutation of the payload must invalidate the signature.
 *
 * The first is the cross-language contract that makes Praxis a "framework",
 * not "a Python hook with some JS on the side". The second is what makes the
 * receipt a *receipt* and not just a log line.
 */

import { describe, it, expect, beforeEach, afterAll } from '@jest/globals';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { signRecord, verifyRecord, _resetKeyCache } from '../lib/receipt.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.dirname(__dirname);

// Isolate each test in its own PRAXIS_HOME so the keyfile doesn't leak
// between cases (and doesn't collide with a real install).
const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'praxis-receipt-'));

function withHome(home, key = null) {
  process.env.PRAXIS_HOME = home;
  if (key) process.env.PRAXIS_RECEIPT_KEY = key;
  else delete process.env.PRAXIS_RECEIPT_KEY;
  _resetKeyCache();
}

afterAll(() => {
  fs.rmSync(tmpRoot, { recursive: true, force: true });
  delete process.env.PRAXIS_HOME;
  delete process.env.PRAXIS_RECEIPT_KEY;
});

describe('receipt — JS round trip', () => {
  beforeEach(() => {
    withHome(fs.mkdtempSync(path.join(tmpRoot, 'js-')));
  });

  it('signs and verifies', () => {
    const signed = signRecord({
      v: 1,
      type: 'alloc',
      sid: 'abc',
      tid: 1,
      ts: 1700000000.0,
      policy_version: '1.1.0',
      payload: { complexity: 7, budget_requested: 16384 },
    });
    expect(signed.sig).toMatch(/^[0-9a-f]{64}$/);
    expect(verifyRecord(signed)).toBe(true);
  });

  it('rejects tampered records', () => {
    const signed = signRecord({
      v: 1,
      type: 'alloc',
      sid: 'abc',
      tid: 1,
      ts: 1700000000.0,
      policy_version: '1.1.0',
      payload: { complexity: 7, budget_requested: 16384 },
    });
    signed.payload.budget_requested = 2048;
    expect(verifyRecord(signed)).toBe(false);
  });

  it('rejects records missing the signature', () => {
    expect(verifyRecord({ v: 1, type: 'alloc' })).toBe(false);
    expect(verifyRecord(null)).toBe(false);
    expect(verifyRecord('not-a-record')).toBe(false);
  });

  it('signature is independent of key insertion order', () => {
    const a = signRecord({ v: 1, type: 'alloc', sid: 'x', tid: 1, ts: 1, policy_version: '1', payload: { a: 1, b: 2 } });
    const b = signRecord({ type: 'alloc', v: 1, payload: { b: 2, a: 1 }, policy_version: '1', ts: 1, sid: 'x', tid: 1 });
    expect(a.sig).toBe(b.sig);
  });
});

describe('receipt — cross-language (Python ↔ JS)', () => {
  it('a Python-signed record verifies from JS with the same key', () => {
    const home = fs.mkdtempSync(path.join(tmpRoot, 'cross-'));
    // Fixed key so both processes sign identically.
    const key = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';
    withHome(home, key);

    const pythonScript = `
import sys, json, os
sys.path.insert(0, ${JSON.stringify(path.join(REPO, 'hooks'))})
import _praxis_lib as pl
rec = {
    "v": 1, "type": "alloc", "sid": "cross-1", "tid": 42,
    "ts": 1700000000.5, "policy_version": "1.1.0",
    "payload": {"complexity": 8, "budget_requested": 16384, "effort": "high"},
}
pl.sign_record(rec)
sys.stdout.write(json.dumps(rec))
`.trim();

    const out = execFileSync('python3', ['-c', pythonScript], {
      encoding: 'utf8',
      env: { ...process.env, PRAXIS_HOME: home, PRAXIS_RECEIPT_KEY: key },
    });
    const rec = JSON.parse(out);

    expect(rec.sig).toMatch(/^[0-9a-f]{64}$/);
    expect(verifyRecord(rec)).toBe(true);

    // And mutating it invalidates from JS just as it would from Python.
    rec.payload.budget_requested = 0;
    expect(verifyRecord(rec)).toBe(false);
  });

  it('a JS-signed record verifies from Python with the same key', () => {
    const home = fs.mkdtempSync(path.join(tmpRoot, 'cross2-'));
    const key = 'fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210';
    withHome(home, key);

    const signed = signRecord({
      v: 1,
      type: 'outcome',
      sid: 'cross-2',
      tid: 7,
      ts: 1700000001.0,
      policy_version: '1.1.0',
      payload: { thinking_used: 5120, stop_reason: 'end_turn' },
    });

    const pythonScript = `
import sys, json
sys.path.insert(0, ${JSON.stringify(path.join(REPO, 'hooks'))})
import _praxis_lib as pl
rec = json.loads(sys.argv[1])
print("ok" if pl.verify_record(rec) else "fail")
`.trim();

    const result = execFileSync('python3', ['-c', pythonScript, JSON.stringify(signed)], {
      encoding: 'utf8',
      env: { ...process.env, PRAXIS_HOME: home, PRAXIS_RECEIPT_KEY: key },
    }).trim();

    expect(result).toBe('ok');
  });
});
