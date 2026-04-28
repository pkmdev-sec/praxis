/**
 * PRAXIS — Receipt primitive (Node twin of ``hooks/_praxis_lib.py``).
 *
 * Mirrors the Python signer byte-for-byte so a record emitted by the hook can
 * be verified from JS and vice-versa. The canonicalisation rule is the load-
 * bearing detail: sorted keys, compact separators, UTF-8, no trailing
 * whitespace. Any divergence in JSON serialisation produces a key miss and a
 * ``verify_record`` false — which is exactly the failure mode we want.
 *
 * This module is intentionally dependency-free (Node stdlib only) so it can
 * be imported from LangChain/LangGraph/etc. without a toolchain bump.
 */

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

export const SCHEMA_VERSION = 1;
export const POLICY_VERSION = '1.1.0';

// ── Paths ───────────────────────────────────────────────────────────────────

export function praxisHome() {
  const override = process.env.PRAXIS_HOME;
  if (override && override.trim()) {
    return override.trim().replace(/^~(?=$|\/)/, os.homedir());
  }

  const thisFile = fileURLToPath(import.meta.url);
  const repoRoot = path.dirname(path.dirname(thisFile));
  const assets = path.join(repoRoot, 'assets');
  try {
    if (fs.statSync(assets).isDirectory()) return assets;
  } catch {
    /* fall through */
  }
  return path.join(os.homedir(), '.praxis');
}

export function ledgerPath(name) {
  const base = praxisHome();
  try {
    fs.mkdirSync(base, { recursive: true });
  } catch {
    /* non-fatal */
  }
  return path.join(base, name);
}

// ── Canonical JSON (matches Python json.dumps(sort_keys=True, separators=(',',':'))) ─

function canonicalize(value) {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return '[' + value.map(canonicalize).join(',') + ']';
  }
  const keys = Object.keys(value).sort();
  const parts = keys.map((k) => JSON.stringify(k) + ':' + canonicalize(value[k]));
  return '{' + parts.join(',') + '}';
}

// ── Keying ──────────────────────────────────────────────────────────────────

let _cachedKey = null;

function loadOrCreateKey() {
  if (_cachedKey) return _cachedKey;

  const env = process.env.PRAXIS_RECEIPT_KEY;
  if (env && env.trim()) {
    try {
      _cachedKey = Buffer.from(env.trim(), 'hex');
      if (_cachedKey.length > 0) return _cachedKey;
    } catch {
      /* fall through to keyfile */
    }
  }

  const keyfile = ledgerPath('receipt.key');
  try {
    if (fs.existsSync(keyfile)) {
      const hex = fs.readFileSync(keyfile, 'utf8').trim();
      _cachedKey = Buffer.from(hex, 'hex');
      if (_cachedKey.length > 0) return _cachedKey;
    }
  } catch {
    /* corrupt keyfile — regenerate */
  }

  _cachedKey = crypto.randomBytes(32);
  try {
    fs.writeFileSync(keyfile, _cachedKey.toString('hex'), { mode: 0o600 });
  } catch {
    /* non-fatal */
  }
  return _cachedKey;
}

/** Testing / integration entry point: wipe the in-memory key cache. */
export function _resetKeyCache() {
  _cachedKey = null;
}

// ── Sign / verify ───────────────────────────────────────────────────────────

export function signRecord(record) {
  const { sig: _drop, ...unsigned } = record;
  void _drop;
  const digest = crypto
    .createHmac('sha256', loadOrCreateKey())
    .update(canonicalize(unsigned), 'utf8')
    .digest('hex');
  return { ...record, sig: digest };
}

export function verifyRecord(record) {
  if (!record || typeof record !== 'object' || typeof record.sig !== 'string') {
    return false;
  }
  const { sig, ...unsigned } = record;
  const expected = crypto
    .createHmac('sha256', loadOrCreateKey())
    .update(canonicalize(unsigned), 'utf8')
    .digest('hex');
  // Length check first so timingSafeEqual doesn't throw.
  if (expected.length !== sig.length) return false;
  return crypto.timingSafeEqual(Buffer.from(expected, 'utf8'), Buffer.from(sig, 'utf8'));
}

export { canonicalize as _canonicalize };
