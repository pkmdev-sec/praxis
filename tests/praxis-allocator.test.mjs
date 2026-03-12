import { describe, it, expect } from '@jest/globals';
import { execSync } from 'child_process';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const hookPath = join(__dirname, '..', 'hooks', 'praxis-allocator.py');

function runHook(input) {
  const result = execSync(`echo '${JSON.stringify(input)}' | python3 "${hookPath}"`, {
    encoding: 'utf8',
    timeout: 5000,
  });
  return JSON.parse(result.trim());
}

describe('praxis-allocator hook', () => {
  it('allocates 0 tokens for simple questions', () => {
    const result = runHook({ prompt: 'What is a variable?' });
    expect(result.max_thinking_tokens).toBeDefined();
    expect(result.complexity_score).toBeLessThanOrEqual(3);
  });

  it('allocates more tokens for complex tasks', () => {
    const simple = runHook({ prompt: 'What is JS?' });
    const complex = runHook({ prompt: 'Design a distributed fault-tolerant microservice architecture with CQRS and event sourcing' });
    expect(complex.max_thinking_tokens).toBeGreaterThanOrEqual(simple.max_thinking_tokens);
  });

  it('respects explicit thinking keywords', () => {
    const result = runHook({ prompt: 'ultrathink about this problem' });
    expect(result.max_thinking_tokens).toBe(32768);
    expect(result.decision).toBe('keyword_override');
  });

  it('handles megathink keyword', () => {
    const result = runHook({ prompt: 'megathink through this design' });
    expect(result.max_thinking_tokens).toBe(16384);
    expect(result.decision).toBe('keyword_override');
  });

  it('auto-scores when no keyword present', () => {
    const result = runHook({ prompt: 'Add a button to the form' });
    expect(result.decision).toBe('auto_scored');
  });

  it('handles empty prompt', () => {
    const result = runHook({ prompt: '' });
    expect(result).toEqual({});
  });

  it('handles empty input gracefully', () => {
    const result = execSync(`echo '{}' | python3 "${hookPath}"`, {
      encoding: 'utf8',
      timeout: 5000,
    });
    expect(JSON.parse(result.trim())).toEqual({});
  });
});
