#!/usr/bin/env node
/**
 * Optimize Session — Auto-optimize thinking budget for a full coding session
 *
 * Demonstrates how Praxis analyzes task complexity and allocates optimal
 * thinking tokens, tracking savings across an entire session.
 *
 * Usage: node examples/optimize-session.mjs
 */
import { scoreComplexity, scoreWithMultiSignal } from '../lib/complexity-scorer.mjs';
import { allocate, getOptimalBudget, getSavingsReport, resetHistory, trackEfficiency } from '../lib/budget-allocator.mjs';
import { trackThinkingCost, getThinkingSavings, resetCostLog } from '../lib/cost-tracker.mjs';
import { detectThinkingLevel, suggestLevel } from '../lib/thinking-keywords.mjs';

// Reset for clean demo
resetHistory();
resetCostLog();

console.log('=== Praxis Session Optimizer ===\n');

// Simulate a realistic coding session
const sessionTasks = [
  { prompt: 'Fix the typo in the README file', expectedQuality: 0.95 },
  { prompt: 'Add input validation to the user registration form using Zod', expectedQuality: 0.88 },
  { prompt: 'Design a distributed caching architecture with Redis cluster for our microservices', expectedQuality: 0.82 },
  { prompt: 'What does the formatDate function do?', expectedQuality: 0.97 },
  { prompt: 'Refactor the authentication module to support OAuth2 with PKCE flow', expectedQuality: 0.85 },
  { prompt: 'Run the test suite', expectedQuality: 0.99 },
  { prompt: 'Implement a real-time collaboration system using CRDTs and WebSockets', expectedQuality: 0.78 },
  { prompt: 'Update the copyright year in the footer component', expectedQuality: 0.98 },
];

console.log('--- Analyzing Tasks ---\n');
console.log('Task'.padEnd(60) + 'Score  Tier        Tokens   Cost');
console.log('-'.repeat(100));

for (const task of sessionTasks) {
  const complexity = scoreComplexity(task.prompt);
  const budget = allocate(complexity);
  const level = suggestLevel(complexity);

  // Track the allocation
  trackEfficiency(budget.tokens, task.expectedQuality);
  trackThinkingCost(budget.tokens, budget.model);

  const shortPrompt = task.prompt.substring(0, 55).padEnd(55);
  console.log(
    `  ${shortPrompt}  ${String(complexity).padStart(2)}/10  ${budget.tier.padEnd(10)}  ${String(budget.tokens).padStart(6)}   ${level.keyword || 'none'}`
  );
}

// Show savings report
console.log('\n--- Session Savings Report ---\n');
const savings = getSavingsReport();
console.log(`  Total allocated:   ${savings.totalAllocated.toLocaleString()} tokens`);
console.log(`  Max possible:      ${savings.maxPossible.toLocaleString()} tokens`);
console.log(`  Tokens saved:      ${savings.tokensSaved.toLocaleString()} tokens`);
console.log(`  Percent saved:     ${savings.percentSaved.toFixed(1)}%`);
console.log(`  Calls optimized:   ${savings.callCount}`);
console.log(`  Avg efficiency:    ${(savings.avgEfficiency * 100).toFixed(1)}%`);

// Show cost savings
console.log('\n--- Cost Savings ---\n');
const costSavings = getThinkingSavings();
console.log(`  Actual cost:       $${costSavings.totalActualCost.toFixed(4)}`);
console.log(`  Without Praxis:    $${costSavings.totalMaxCost.toFixed(4)}`);
console.log(`  Money saved:       $${costSavings.totalSaved.toFixed(4)}`);
console.log(`  Percent saved:     ${costSavings.percentSaved.toFixed(1)}%`);
