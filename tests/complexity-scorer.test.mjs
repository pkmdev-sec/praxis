import { describe, it, expect } from '@jest/globals';
import {
  scoreComplexity,
  extractSignals,
  classifyTaskType,
  TASK_TYPES,
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
