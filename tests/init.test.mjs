/**
 * PRAXIS — `praxis init` tests.
 *
 * Pinning invariants so we never silently regress the hook format
 * Claude Code expects. The bug this commit fixes: the previous
 * implementation emitted {command: ...} flat, which current Claude
 * Code silently ignores — hooks never fire, receipts never land.
 */

import { describe, it, expect, beforeEach, afterEach } from '@jest/globals';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.dirname(__dirname);
const PRAXIS_BIN = path.join(REPO, 'bin', 'praxis');

let fakeHome;

beforeEach(() => {
  fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), 'praxis-init-'));
  fs.mkdirSync(path.join(fakeHome, '.claude'), { recursive: true });
});

afterEach(() => {
  fs.rmSync(fakeHome, { recursive: true, force: true });
});

function runInit(env = {}) {
  return execFileSync('node', [PRAXIS_BIN, 'init'], {
    env: { ...process.env, HOME: fakeHome, ...env },
    encoding: 'utf8',
  });
}

function readSettings() {
  return JSON.parse(
    fs.readFileSync(path.join(fakeHome, '.claude', 'settings.json'), 'utf8'),
  );
}

describe('praxis init — hook shape', () => {
  it('emits the nested {hooks: [{type, command, timeout}]} format', () => {
    runInit();
    const s = readSettings();

    // Claude Code contract: hooks[event] is an array of blocks.
    // Each block is {hooks: [{type, command, timeout?}]}.
    expect(Array.isArray(s.hooks.UserPromptSubmit)).toBe(true);
    expect(s.hooks.UserPromptSubmit).toHaveLength(1);

    const block = s.hooks.UserPromptSubmit[0];
    expect(Array.isArray(block.hooks)).toBe(true);
    expect(block.hooks).toHaveLength(1);

    const hook = block.hooks[0];
    expect(hook.type).toBe('command');
    expect(hook.command).toMatch(/python3 .*praxis-allocator\.py/);
    expect(typeof hook.timeout).toBe('number');
  });

  it('installs both UserPromptSubmit and Stop hooks', () => {
    runInit();
    const s = readSettings();
    expect(s.hooks.UserPromptSubmit[0].hooks[0].command).toMatch(/praxis-allocator/);
    expect(s.hooks.Stop[0].hooks[0].command).toMatch(/praxis-outcome/);
  });

  it('preserves existing unrelated hooks', () => {
    // Pre-seed with someone else's hook to verify we don't clobber.
    const existing = {
      env: { FOO: 'bar' },
      hooks: {
        PreToolUse: [
          { hooks: [{ type: 'command', command: 'other-hook.sh', timeout: 10 }] },
        ],
      },
    };
    fs.writeFileSync(
      path.join(fakeHome, '.claude', 'settings.json'),
      JSON.stringify(existing),
    );

    runInit();
    const s = readSettings();
    expect(s.env.FOO).toBe('bar');
    expect(s.hooks.PreToolUse[0].hooks[0].command).toBe('other-hook.sh');
    expect(s.hooks.UserPromptSubmit).toBeDefined();
    expect(s.hooks.Stop).toBeDefined();
  });

  it('is idempotent — double-init does not duplicate hooks', () => {
    runInit();
    runInit();
    const s = readSettings();
    expect(s.hooks.UserPromptSubmit).toHaveLength(1);
    expect(s.hooks.UserPromptSubmit[0].hooks).toHaveLength(1);
    expect(s.hooks.Stop).toHaveLength(1);
    expect(s.hooks.Stop[0].hooks).toHaveLength(1);
  });

  it('is safe when there is no pre-existing settings.json', () => {
    fs.rmSync(path.join(fakeHome, '.claude', 'settings.json'), { force: true });
    runInit();
    const s = readSettings();
    expect(s.hooks.UserPromptSubmit).toBeDefined();
    expect(s.hooks.Stop).toBeDefined();
  });
});
