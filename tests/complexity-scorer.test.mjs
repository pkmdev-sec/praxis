import { describe, it, expect } from '@jest/globals';
import {
  scoreComplexity,
  extractSignals,
  classifyTaskType,
  TASK_TYPES,
  scoreWithMultiSignal,
  analyzeCodeComplexity,
} from '../lib/complexity-scorer.mjs';

describe('scoreComplexity', () => {
  it('scores simple questions as 1-2', () => {
    const score = scoreComplexity('What is a variable?');
    expect(score).toBeGreaterThanOrEqual(1);
    expect(score).toBeLessThanOrEqual(3);
  });

  it('scores code modifications as 3-5', () => {
    const score = scoreComplexity('Fix the bug in the login form');
    expect(score).toBeGreaterThanOrEqual(3);
    expect(score).toBeLessThanOrEqual(6);
  });

  it('scores architecture tasks as 6-8', () => {
    const score = scoreComplexity('Design a scalable distributed system for handling millions of users');
    expect(score).toBeGreaterThanOrEqual(5);
    expect(score).toBeLessThanOrEqual(10);
  });

  it('scores multi-step debugging as 8-10', () => {
    const score = scoreComplexity('Debug the complex intermittent race condition causing a memory leak in the concurrent request handler');
    expect(score).toBeGreaterThanOrEqual(6);
    expect(score).toBeLessThanOrEqual(10);
  });

  it('returns 1 for empty input', () => {
    expect(scoreComplexity('')).toBe(1);
    expect(scoreComplexity(null)).toBe(1);
    expect(scoreComplexity(undefined)).toBe(1);
  });

  it('returns scores within 1-10 range', () => {
    const prompts = [
      'hi',
      'explain recursion',
      'add a button to the navbar',
      'refactor the authentication module to use OAuth2',
      'design a microservice architecture for an e-commerce platform with distributed caching',
    ];
    for (const p of prompts) {
      const score = scoreComplexity(p);
      expect(score).toBeGreaterThanOrEqual(1);
      expect(score).toBeLessThanOrEqual(10);
    }
  });

  it('gives higher scores to longer, more complex prompts', () => {
    const simple = scoreComplexity('What is JS?');
    const complex = scoreComplexity(
      'Design a distributed microservice architecture for a real-time trading platform with fault tolerance, horizontal scaling, event sourcing, and CQRS patterns. Consider security implications and performance optimization strategies.'
    );
    expect(complex).toBeGreaterThan(simple);
  });
});

describe('extractSignals', () => {
  it('extracts keywords from prompt', () => {
    const signals = extractSignals('Fix the bug in the login form');
    expect(signals.keywords).toContain('fix');
    expect(signals.keywords).toContain('bug');
  });

  it('detects question type', () => {
    expect(extractSignals('What is a closure?').questionType).toBe('factual');
    expect(extractSignals('How does React work?').questionType).toBe('explanatory');
    expect(extractSignals('Implement a cache system').questionType).toBe('imperative');
  });

  it('calculates word count', () => {
    const signals = extractSignals('one two three four five');
    expect(signals.wordCount).toBe(5);
  });

  it('handles empty input', () => {
    const signals = extractSignals('');
    expect(signals.keywords).toEqual([]);
    expect(signals.wordCount).toBe(0);
  });

  it('identifies matched tier', () => {
    const simple = extractSignals('What is a variable?');
    expect(simple.matchedTier).toBe('simple');

    const complex = extractSignals('Design a scalable system');
    expect(complex.matchedTier).toBe('complex');
  });
});

describe('classifyTaskType', () => {
  it('classifies questions', () => {
    expect(classifyTaskType('What is a promise?')).toBe(TASK_TYPES.QUESTION);
  });

  it('classifies implementation tasks', () => {
    expect(classifyTaskType('Create a new REST API endpoint')).toBe(TASK_TYPES.IMPLEMENTATION);
    expect(classifyTaskType('Add pagination to the list view')).toBe(TASK_TYPES.IMPLEMENTATION);
  });

  it('classifies architecture tasks', () => {
    expect(classifyTaskType('Design a microservice architecture')).toBe(TASK_TYPES.ARCHITECTURE);
  });

  it('classifies debugging tasks', () => {
    expect(classifyTaskType('Debug the race condition in the worker pool')).toBe(TASK_TYPES.DEBUGGING);
  });

  it('classifies review tasks', () => {
    expect(classifyTaskType('Review this pull request for security issues')).toBe(TASK_TYPES.REVIEW);
  });

  it('defaults to question for unknown input', () => {
    expect(classifyTaskType('')).toBe(TASK_TYPES.QUESTION);
    expect(classifyTaskType(null)).toBe(TASK_TYPES.QUESTION);
  });
});

// P1 ENHANCEMENT TESTS: Multi-signal scoring
describe('scoreWithMultiSignal', () => {

  it('provides detailed breakdown of complexity signals', () => {
    const result = scoreWithMultiSignal('Fix the bug in auth.js and update the login() function');
    expect(result).toHaveProperty('totalScore');
    expect(result).toHaveProperty('breakdown');
    expect(result.breakdown).toHaveProperty('keywordScore');
    expect(result.breakdown).toHaveProperty('lengthScore');
    expect(result.breakdown).toHaveProperty('questionScore');
    expect(result.breakdown).toHaveProperty('structuralScore');
    expect(result.breakdown).toHaveProperty('questionCount');
    expect(result.breakdown).toHaveProperty('codeBlockCount');
    expect(result.breakdown).toHaveProperty('hasCodeReferences');
    expect(result.breakdown).toHaveProperty('technicalTermCount');
  });

  it('detects code references in prompts', () => {
    const withCode = scoreWithMultiSignal('Update the `authenticate()` function in auth.js');
    expect(withCode.breakdown.hasCodeReferences).toBe(true);

    const noCode = scoreWithMultiSignal('What is authentication?');
    expect(noCode.breakdown.hasCodeReferences).toBe(false);
  });

  it('counts technical terms correctly', () => {
    const technical = scoreWithMultiSignal('Design an API with JWT authentication and OAuth2 authorization using REST endpoints');
    expect(technical.breakdown.technicalTermCount).toBeGreaterThan(3);

    const simple = scoreWithMultiSignal('What is a variable?');
    expect(simple.breakdown.technicalTermCount).toBe(0);
  });

  it('counts multiple questions', () => {
    const multiQuestion = scoreWithMultiSignal('What is async? How does it work? When should I use it?');
    expect(multiQuestion.breakdown.questionCount).toBe(3);
  });

  it('counts code blocks', () => {
    const withCodeBlocks = scoreWithMultiSignal('Fix this:\n```js\nfunction test() {}\n```\nAnd this:\n```js\nfunction test2() {}\n```');
    expect(withCodeBlocks.breakdown.codeBlockCount).toBe(2);
  });

  // Edge case: empty input
  it('handles empty input gracefully', () => {
    expect(() => scoreWithMultiSignal('')).not.toThrow();
    expect(() => scoreWithMultiSignal(null)).not.toThrow();
    expect(() => scoreWithMultiSignal(undefined)).not.toThrow();
    const result = scoreWithMultiSignal('');
    expect(result.totalScore).toBe(1);
  });

  // Edge case: very long prompt
  it('handles very long prompts', () => {
    const longPrompt = 'design a system '.repeat(100);
    const result = scoreWithMultiSignal(longPrompt);
    expect(result.totalScore).toBeGreaterThanOrEqual(1);
    expect(result.totalScore).toBeLessThanOrEqual(10);
  });

  // Edge case: special characters
  it('handles special characters', () => {
    const specialPrompt = 'Fix: ⚠️ ERROR!!! [URGENT] @@@';
    expect(() => scoreWithMultiSignal(specialPrompt)).not.toThrow();
    const special = scoreWithMultiSignal(specialPrompt);
    expect(special.totalScore).toBeGreaterThanOrEqual(1);
  });

  // Edge case: only code
  it('handles prompts with only code blocks', () => {
    const onlyCode = scoreWithMultiSignal('```js\nfunction test() { return 42; }\n```');
    expect(onlyCode.breakdown.codeBlockCount).toBe(1);
    expect(onlyCode.totalScore).toBeGreaterThan(1);
  });

  // Edge case: invalid input type
  it('throws error for invalid input type', () => {
    expect(() => scoreWithMultiSignal(123)).toThrow();
    expect(() => scoreWithMultiSignal({})).toThrow();
  });
});

describe('analyzeCodeComplexity', () => {

  it('detects code blocks in prompts', () => {
    const result = analyzeCodeComplexity('Fix:\n```js\nconst x = 1;\n```');
    expect(result.hasCode).toBe(true);
    expect(result.codeBlockCount).toBe(1);
  });

  it('detects inline code', () => {
    const result = analyzeCodeComplexity('Update the `fetchData()` function');
    expect(result.hasCode).toBe(true);
    expect(result.hasInlineCode).toBe(true);
  });

  it('extracts file references', () => {
    const result = analyzeCodeComplexity('Fix bugs in auth.js, server.py, and config.json');
    expect(result.fileReferences.length).toBeGreaterThan(0);
    expect(result.fileReferences).toContain('auth.js');
  });

  it('extracts function references', () => {
    const result = analyzeCodeComplexity('Update fetchData() and parseResponse() functions');
    expect(result.functionReferences.length).toBeGreaterThan(0);
  });

  it('classifies complexity correctly', () => {
    const low = analyzeCodeComplexity('What is JavaScript?');
    expect(low.complexity).toBe('low');

    const medium = analyzeCodeComplexity('Fix the bug in `login()` function in auth.js');
    expect(medium.complexity).toBe('medium');

    const high = analyzeCodeComplexity('Refactor auth.js, user.js, session.js:\n```js\ncode1\n```\n```js\ncode2\n```\n```js\ncode3\n```');
    expect(high.complexity).toBe('high');
  });

  // Edge case: empty input
  it('handles empty input', () => {
    const result = analyzeCodeComplexity('');
    expect(result.hasCode).toBe(false);
    expect(result.complexity).toBe('low');
  });

  // Edge case: null/undefined
  it('handles null/undefined input', () => {
    expect(() => analyzeCodeComplexity(null)).not.toThrow();
    expect(() => analyzeCodeComplexity(undefined)).not.toThrow();
  });

  // Edge case: no code at all
  it('handles prompts with no code references', () => {
    const result = analyzeCodeComplexity('What is the weather today?');
    expect(result.hasCode).toBe(false);
    expect(result.fileReferences.length).toBe(0);
    expect(result.functionReferences.length).toBe(0);
  });
});
