/**
 * PRAXIS — Complexity Scorer
 * Scores task complexity to determine optimal thinking budget allocation.
 */

const TASK_TYPES = {
  QUESTION: 'question',
  IMPLEMENTATION: 'implementation',
  ARCHITECTURE: 'architecture',
  DEBUGGING: 'debugging',
  REVIEW: 'review',
};

const SIGNAL_WEIGHTS = {
  keywords: 0.3,
  length: 0.2,
  questionType: 0.3,
  structuralComplexity: 0.2,
};

// Keyword groups mapped to complexity tiers
const KEYWORD_TIERS = {
  simple: {
    score: 1,
    patterns: [
      /\bwhat is\b/i, /\bdefine\b/i, /\bexplain\b/i, /\bhow to\b/i,
      /\blist\b/i, /\bshow me\b/i, /\btell me\b/i, /\bwhat does\b/i,
    ],
  },
  moderate: {
    score: 4,
    patterns: [
      /\bfix\b/i, /\bmodify\b/i, /\bchange\b/i, /\bupdate\b/i,
      /\badd\b/i, /\bremove\b/i, /\brefactor\b/i, /\bimplement\b/i,
      /\bcreate\b/i, /\bwrite\b/i, /\bbug\b/i, /\berror\b/i,
    ],
  },
  complex: {
    score: 7,
    patterns: [
      /\bdesign\b/i, /\barchitect\b/i, /\bsystem\b/i, /\bscalable\b/i,
      /\bmigrat/i, /\boptimiz/i, /\bperformance\b/i, /\bsecurity\b/i,
      /\bdistributed\b/i, /\bmicroservic/i, /\bpipeline\b/i,
    ],
  },
  advanced: {
    score: 9,
    patterns: [
      /\bdebug\s+complex/i, /\brace\s+condition/i, /\bmemory\s+leak/i,
      /\bconcurrency/i, /\bdeadlock/i, /\bmulti.?step/i,
      /\broot\s+cause/i, /\bintermittent/i, /\bnondeterministic/i,
      /\bcomplex\s+issue/i, /\bfull\s+stack/i,
    ],
  },
};

/**
 * Extract signals from a prompt for complexity analysis.
 * @param {string} prompt - The user prompt to analyze.
 * @returns {{ keywords: string[], length: number, questionType: string, matchedTier: string|null, wordCount: number }}
 */
export function extractSignals(prompt) {
  try {
    // Input validation: null/undefined/empty prompts should return sensible defaults
    if (prompt === null || prompt === undefined || prompt === '') {
      return { keywords: [], length: 0, questionType: 'unknown', matchedTier: null, wordCount: 0 };
    }
    if (typeof prompt !== 'string') {
      throw new Error(`Invalid prompt: expected string, got ${typeof prompt}`);
    }

    const keywords = [];
    let matchedTier = null;
    let highestScore = 0;

    for (const [tier, { score, patterns }] of Object.entries(KEYWORD_TIERS)) {
      for (const pattern of patterns) {
        const match = prompt.match(pattern);
        if (match) {
          keywords.push(match[0].toLowerCase());
          if (score > highestScore) {
            highestScore = score;
            matchedTier = tier;
          }
        }
      }
    }

    const questionType = detectQuestionType(prompt);
    const wordCount = prompt.trim().split(/\s+/).filter(Boolean).length;

    return {
      keywords: [...new Set(keywords)],
      length: prompt.length,
      questionType,
      matchedTier,
      wordCount,
    };
  } catch (error) {
    console.error(`Error in extractSignals: ${error.message}`);
    throw error;
  }
}

/**
 * Detect the type of question being asked.
 * @param {string} prompt
 * @returns {string}
 */
function detectQuestionType(prompt) {
  if (/\?$/.test(prompt.trim())) {
    if (/^(what|who|where|when|which)\b/i.test(prompt)) return 'factual';
    if (/^(how|why)\b/i.test(prompt)) return 'explanatory';
    if (/^(can|could|should|would|is|are|do|does)\b/i.test(prompt)) return 'decisional';
  }
  if (/\b(implement|create|build|write|add|make)\b/i.test(prompt)) return 'imperative';
  if (/\b(fix|debug|solve|resolve|troubleshoot)\b/i.test(prompt)) return 'diagnostic';
  if (/\b(review|check|audit|assess|evaluate)\b/i.test(prompt)) return 'evaluative';
  if (/\b(design|architect|plan|propose)\b/i.test(prompt)) return 'strategic';
  return 'general';
}

/**
 * Classify the task type from a prompt.
 * @param {string} prompt - The user prompt.
 * @returns {string} One of: question, implementation, architecture, debugging, review
 */
export function classifyTaskType(prompt) {
  try {
    // Input validation: null/undefined/empty prompts should return sensible default
    if (prompt === null || prompt === undefined || prompt === '' || typeof prompt !== 'string') {
      return TASK_TYPES.QUESTION;
    }

    const lower = prompt.toLowerCase();

    // Check for debugging signals first (highest priority match)
    if (/\b(debug|fix|bug|error|crash|broken|failing|issue|troubleshoot|stack\s*trace)\b/.test(lower)) {
      // If it's a complex debugging scenario, keep as debugging
      if (/\b(complex|intermittent|race|deadlock|memory|leak|root\s+cause)\b/.test(lower)) {
        return TASK_TYPES.DEBUGGING;
      }
      // Simple fix requests are implementation
      if (/\b(fix|update|change|modify)\b/.test(lower) && !/\b(why|how come|cause)\b/.test(lower)) {
        return TASK_TYPES.IMPLEMENTATION;
      }
      return TASK_TYPES.DEBUGGING;
    }

    // Architecture signals
    if (/\b(design|architect|system|scalab|distribut|microservic|pipeline|infrastruct|migrat)\b/.test(lower)) {
      return TASK_TYPES.ARCHITECTURE;
    }

    // Review signals
    if (/\b(review|audit|check|assess|evaluate|code\s+review|pr\s+review)\b/.test(lower)) {
      return TASK_TYPES.REVIEW;
    }

    // Implementation signals
    if (/\b(implement|create|build|write|add|remove|refactor|update|deploy|install|configure)\b/.test(lower)) {
      return TASK_TYPES.IMPLEMENTATION;
    }

    // Default: question
    return TASK_TYPES.QUESTION;
  } catch (error) {
    console.error(`Error in classifyTaskType: ${error.message}`);
    return TASK_TYPES.QUESTION;
  }
}

/**
 * Score the complexity of a prompt on a 1-10 scale.
 * @param {string} prompt - The user prompt to score.
 * @returns {number} Complexity score from 1 to 10.
 */
export function scoreComplexity(prompt) {
  try {
    // Input validation: null/undefined/empty prompts should return sensible default (1 = minimum complexity)
    if (prompt === null || prompt === undefined || prompt === '') {
      return 1;
    }
    if (typeof prompt !== 'string') {
      throw new Error(`Invalid prompt: expected string, got ${typeof prompt}`);
    }

    const signals = extractSignals(prompt);
    const taskType = classifyTaskType(prompt);

    // Base score from keyword tier matching
    let keywordScore = 1;
    if (signals.matchedTier) {
      keywordScore = KEYWORD_TIERS[signals.matchedTier].score;
    }

    // Length-based score (longer prompts tend to be more complex)
    let lengthScore;
    if (signals.wordCount <= 10) lengthScore = 1;
    else if (signals.wordCount <= 30) lengthScore = 3;
    else if (signals.wordCount <= 80) lengthScore = 5;
    else if (signals.wordCount <= 150) lengthScore = 7;
    else lengthScore = 9;

    // Question type score
    const questionTypeScores = {
      factual: 1,
      explanatory: 3,
      decisional: 4,
      imperative: 5,
      diagnostic: 7,
      evaluative: 5,
      strategic: 8,
      general: 3,
      unknown: 2,
    };
    const questionScore = questionTypeScores[signals.questionType] || 3;

    // Task type score
    const taskTypeScores = {
      [TASK_TYPES.QUESTION]: 2,
      [TASK_TYPES.IMPLEMENTATION]: 5,
      [TASK_TYPES.REVIEW]: 5,
      [TASK_TYPES.DEBUGGING]: 7,
      [TASK_TYPES.ARCHITECTURE]: 8,
    };
    const taskScore = taskTypeScores[taskType] || 3;

    // Structural complexity: count code blocks, lists, multiple questions
    let structuralScore = 1;
    const codeBlocks = (prompt.match(/```/g) || []).length / 2;
    const questionMarks = (prompt.match(/\?/g) || []).length;
    const bullets = (prompt.match(/^[\s]*[-*]\s/gm) || []).length;
    structuralScore = Math.min(10, 1 + codeBlocks * 2 + (questionMarks - 1) * 1.5 + bullets * 0.5);

    // Weighted combination
    const raw =
      keywordScore * SIGNAL_WEIGHTS.keywords +
      lengthScore * SIGNAL_WEIGHTS.length +
      questionScore * SIGNAL_WEIGHTS.questionType +
      structuralScore * SIGNAL_WEIGHTS.structuralComplexity;

    // Blend with task type score
    const blended = raw * 0.6 + taskScore * 0.4;

    // Clamp to 1-10 and round
    return Math.max(1, Math.min(10, Math.round(blended)));
  } catch (error) {
    console.error(`Error in scoreComplexity: ${error.message}`);
    // Return minimum complexity score as fallback
    return 1;
  }
}

export { TASK_TYPES, KEYWORD_TIERS };
