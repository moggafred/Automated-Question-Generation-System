/**
 * Client-side state: persisted preferences plus the active assessment session.
 *
 * Preferences survive reloads via localStorage. The active session (the quiz
 * being taken and the learner's answers) is kept in memory only, so answers are
 * never written to disk before submission.
 */

const KEYS = {
  theme: 'aqg.theme',
  sidebar: 'aqg.sidebar',
  rail: 'aqg.rail',
  generate: 'aqg.generate-prefs',
  study: 'aqg.study-prefs',
};

function readJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? { ...fallback, ...JSON.parse(raw) } : { ...fallback };
  } catch {
    return { ...fallback };
  }
}

function writeJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* Private mode: preferences simply do not persist. */
  }
}

function readText(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeText(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* Ignore quota or privacy errors. */
  }
}

// -- Theme ---------------------------------------------------------------

export function getTheme() {
  const stored = readText(KEYS.theme);
  if (stored === 'light' || stored === 'dark') return stored;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function setTheme(theme) {
  const value = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', value);
  writeText(KEYS.theme, value);
  document.dispatchEvent(new CustomEvent('aqg:themechange', { detail: value }));
  return value;
}

export function toggleTheme() {
  return setTheme(getTheme() === 'dark' ? 'light' : 'dark');
}

// -- Sidebar -------------------------------------------------------------

export function isSidebarCollapsed() {
  return readText(KEYS.sidebar) === 'collapsed';
}

export function setSidebarCollapsed(collapsed) {
  writeText(KEYS.sidebar, collapsed ? 'collapsed' : 'expanded');
  return collapsed;
}

// -- Right-hand side panel (rail) -----------------------------------------

export function isRailHidden() {
  return readText(KEYS.rail) === 'hidden';
}

export function setRailHidden(hidden) {
  writeText(KEYS.rail, hidden ? 'hidden' : 'shown');
  return hidden;
}

// -- Platform metadata (limits, vocabularies) ---------------------------

const metadata = {
  status: null,
  limits: null,
  questionTypes: [],
  difficultyLevels: [],
  studyTypes: [],
  assessmentTypes: [],
};

export function getMetadata() {
  return metadata;
}

export function setStatus(status) {
  metadata.status = status;
  if (status?.limits) metadata.limits = status.limits;
  if (status?.question_types?.length) metadata.questionTypes = status.question_types;
  if (status?.difficulty_levels?.length) metadata.difficultyLevels = status.difficulty_levels;
  if (status?.study_material_types?.length) metadata.studyTypes = status.study_material_types;
  return status;
}

/** Normalised upload and generation limits with safe fallbacks. */
export function getLimits() {
  return {
    maxUploadBytes: 10 * 1024 * 1024,
    maxUploadMb: 10,
    allowedExtensions: ['.pdf', '.txt'],
    minQuestions: 1,
    maxQuestions: 20,
    defaultQuestions: 5,
    quickCounts: [5, 10, 15, 20],
    ...(metadata.limits || {}),
  };
}

export function getQuestionTypes() {
  return metadata.questionTypes.length ? metadata.questionTypes : DEFAULT_QUESTION_TYPES;
}

export function getDifficultyLevels() {
  return metadata.difficultyLevels.length
    ? metadata.difficultyLevels
    : [
        { value: 'easy', label: 'Easy' },
        { value: 'medium', label: 'Medium' },
        { value: 'hard', label: 'Hard' },
      ];
}

export function getStudyTypes() {
  return metadata.studyTypes.length
    ? metadata.studyTypes
    : [
        { value: 'summary', label: 'Summary' },
        { value: 'key-concepts', label: 'Key Concepts' },
        { value: 'flashcards', label: 'Flashcards' },
        { value: 'definitions', label: 'Important Definitions' },
        { value: 'revision-notes', label: 'Revision Notes' },
        { value: 'all', label: 'Full Study Pack' },
      ];
}

const DEFAULT_QUESTION_TYPES = [
  { value: 'multiple-choice', label: 'Multiple Choice' },
  { value: 'true-false', label: 'True / False' },
  { value: 'short-answer', label: 'Short Answer' },
  { value: 'fill-in-the-blank', label: 'Fill in the Blank' },
  { value: 'essay', label: 'Essay' },
  { value: 'scenario-based', label: 'Scenario-Based' },
  { value: 'case-study', label: 'Case Study' },
  { value: 'application', label: 'Application' },
  { value: 'mixed', label: 'Mixed' },
];

// -- Form preferences ----------------------------------------------------

export function getGeneratePrefs() {
  return readJson(KEYS.generate, {
    type: 'multiple-choice',
    count: 5,
    difficulty: 'medium',
    topic: '',
    instructions: '',
  });
}

export function saveGeneratePrefs(patch) {
  const next = { ...getGeneratePrefs(), ...patch };
  writeJson(KEYS.generate, next);
  return next;
}

export function getStudyPrefs() {
  return readJson(KEYS.study, { type: 'summary', topic: '' });
}

export function saveStudyPrefs(patch) {
  const next = { ...getStudyPrefs(), ...patch };
  writeJson(KEYS.study, next);
  return next;
}

// -- Active assessment session (in memory only) --------------------------

let session = null;

/** Stores the quiz currently being taken plus accumulated timing. */
export function startSession(quiz) {
  session = {
    quiz,
    quizId: quiz.quiz_id,
    answers: new Map(),
    startedAt: Date.now(),
    perQuestionStartedAt: new Map(),
  };
  return session;
}

export function getSession() {
  return session;
}

export function hasSession(quizId) {
  return Boolean(session && (!quizId || session.quizId === quizId));
}

/** Records an answer, storing the option text (never any answer key). */
export function setAnswer(questionId, value) {
  if (!session) return;
  session.answers.set(Number(questionId), String(value ?? ''));
  session.perQuestionStartedAt.set(Number(questionId), Date.now());
}

export function clearAnswer(questionId) {
  if (!session) return;
  session.answers.delete(Number(questionId));
}

/** Current answer for a question, or an empty string when unanswered. */
export function getAnswer(questionId) {
  if (!session) return '';
  return session.answers.get(Number(questionId)) ?? '';
}

/** Every answer, including blank ones so blanks can be graded as unanswered. */
export function collectAnswers() {
  if (!session) return [];
  const questions = session.quiz.questions || [];
  return questions.map((question) => ({
    question_id: question.id,
    answer: session.answers.get(question.id) ?? '',
    time_spent_seconds: estimateTimeSpent(question.id),
  }));
}

export function answeredCount() {
  if (!session) return 0;
  let count = 0;
  for (const value of session.answers.values()) {
    if (String(value ?? '').trim()) count += 1;
  }
  return count;
}

export function elapsedSeconds() {
  if (!session) return 0;
  return Math.round((Date.now() - session.startedAt) / 1000);
}

function estimateTimeSpent(questionId) {
  if (!session) return 0;
  const started = session.perQuestionStartedAt.get(Number(questionId));
  if (!started) return 0;
  return Math.max(0, Math.round((Date.now() - started) / 1000));
}

export function endSession() {
  const finished = session;
  session = null;
  return finished;
}

/** Restores a submitted result so the review screen survives a reload. */
const resultKey = 'aqg.last-result';

export function saveLastResult(result) {
  try {
    localStorage.setItem(resultKey, JSON.stringify(result));
  } catch {
    /* Non-fatal: the review screen still works for this session. */
  }
}

export function getLastResult() {
  try {
    const raw = localStorage.getItem(resultKey);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function clearLastResult() {
  try {
    localStorage.removeItem(resultKey);
  } catch {
    /* Ignore. */
  }
}