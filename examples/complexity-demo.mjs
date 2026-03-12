#!/usr/bin/env node
/**
 * Complexity Demo — Show complexity scoring on sample prompts
 *
 * Demonstrates how Praxis scores prompt complexity using multiple
 * signals including keywords, length, structure, and task type.
 *
 * Usage: node examples/complexity-demo.mjs
 */
import { scoreComplexity, scoreWithMultiSignal, classifyTaskType, extractSignals, analyzeCodeComplexity } from '../lib/complexity-scorer.mjs';
import { suggestLevel, getKeywordMap } from '../lib/thinking-keywords.mjs';
import { allocate, BUDGET_TIERS } from '../lib/budget-allocator.mjs';

console.log('=== Praxis Complexity Scoring Demo ===\n');

// Show budget tiers
console.log('--- Budget Tiers ---\n');
for (const [name, config] of Object.entries(BUDGET_TIERS)) {
  console.log(`  ${name.padEnd(8)} ${String(config.tokens).padStart(6)} tokens`);
}

// Show thinking keywords
console.log('\n--- Thinking Keywords ---\n');
const keywords = getKeywordMap();
for (const [keyword, info] of Object.entries(keywords)) {
  console.log(`  ${keyword.padEnd(12)} → ${info.tokens} tokens (${info.level})`);
}

// Demonstrate scoring on diverse prompts
const prompts = [
  // Simple tasks (low complexity)
  'What time is it?',
  'Fix the typo on line 42',
  'List all files in the src directory',

  // Medium tasks
  'Add error handling to the API endpoints',
  'Write unit tests for the UserService class',
  'Refactor this function to use async/await',

  // Complex tasks
  'Design a microservices architecture with event sourcing and CQRS',
  'Implement a distributed consensus algorithm for our cluster',
  'Build a real-time collaborative editor using operational transforms with conflict resolution',

  // Code-heavy prompts
  'Review this code:\n```javascript\nfunction fibonacci(n) {\n  if (n <= 1) return n;\n  return fibonacci(n-1) + fibonacci(n-2);\n}\n```\nOptimize it for large values of n.',
];

console.log('\n--- Prompt Analysis ---\n');

for (const prompt of prompts) {
  const score = scoreComplexity(prompt);
  const multiSignal = scoreWithMultiSignal(prompt);
  const taskType = classifyTaskType(prompt);
  const budget = allocate(score);
  const level = suggestLevel(score);

  const shortPrompt = prompt.split('\n')[0].substring(0, 65);

  console.log(`  "${shortPrompt}${prompt.length > 65 ? '...' : ''}"`);
  console.log(`    Type: ${taskType}  |  Score: ${score}/10  |  Tier: ${budget.tier}  |  Tokens: ${budget.tokens}`);

  if (multiSignal.breakdown) {
    const b = multiSignal.breakdown;
    console.log(`    Signals: keywords=${b.keywordScore?.toFixed(1) || '?'}, length=${b.lengthScore?.toFixed(1) || '?'}, question=${b.questionScore?.toFixed(1) || '?'}, structure=${b.structuralScore?.toFixed(1) || '?'}`);
  }
  console.log();
}

// Demonstrate code complexity analysis
console.log('--- Code Complexity Analysis ---\n');
const codePrompt = `Review and fix the authentication middleware:
\`\`\`javascript
async function authMiddleware(req, res, next) {
  const token = req.headers.authorization?.split(' ')[1];
  if (!token) return res.status(401).json({ error: 'No token' });
  try {
    const decoded = jwt.verify(token, process.env.JWT_SECRET);
    req.user = await User.findById(decoded.id);
    next();
  } catch (err) {
    res.status(401).json({ error: 'Invalid token' });
  }
}
\`\`\`
Add refresh token support, rate limiting, and proper error logging.`;

const codeAnalysis = analyzeCodeComplexity(codePrompt);
console.log('Code analysis:');
console.log(`  Has code blocks: ${codeAnalysis.hasCode}`);
console.log(`  Code block count: ${codeAnalysis.codeBlockCount}`);
console.log(`  File references: ${codeAnalysis.fileReferences.length}`);
console.log(`  Function references: ${codeAnalysis.functionReferences.length}`);
console.log(`  Code complexity: ${codeAnalysis.complexity}`);

const finalScore = scoreComplexity(codePrompt);
const finalBudget = allocate(finalScore);
console.log(`\n  Final score: ${finalScore}/10 → ${finalBudget.tier} (${finalBudget.tokens} tokens)`);
