/**
 * Generate: upload a document and produce a grounded, auto-graded assessment.
 */

import { generateQuiz, getLimits } from '../api.js';
import {
  escapeHtml,
  formatBytes,
  hydrateIcons,
  titleCase,
} from '../dom.js';
import { icon } from '../icons.js';
import {
  getDifficultyLevels,
  getGeneratePrefs,
  getLimits as getStoredLimits,
  getQuestionTypes,
  saveGeneratePrefs,
} from '../store.js';
import {
  bindDropzone,
  renderFileSelection,
  setStageProgress,
  stagesMarkup,
  validateFile,
} from '../upload.js';
import { toastError, toastSuccess } from '../toast.js';

const STAGES = [
  { id: 'upload', label: 'Reading your document' },
  { id: 'retrieve', label: 'Finding the relevant passages' },
  { id: 'generate', label: 'Writing and validating questions' },
  { id: 'save', label: 'Saving the assessment' },
];

const TYPE_HINTS = {
  'multiple-choice': 'Best for quick revision and self-testing.',
  'true-false': 'Fastest format for reinforcing facts and concepts.',
  'short-answer': 'Practise recalling definitions and explanations.',
  'fill-in-the-blank': 'Targets precise terminology from the document.',
  essay: 'Extended written responses scored with partial credit.',
  'scenario-based': 'Apply the material to a realistic situation.',
  'case-study': 'One grounded case narrative with several sub-questions.',
  application: 'Use the material to solve a practical problem.',
  mixed: 'A balanced mix of every supported format.',
};

const DIFFICULTY_HINTS = {
  easy: 'Recall and recognition.',
  medium: 'Understanding and explanation.',
  hard: 'Analysis, application and evaluation.',
};

export default async function render({ query = {} } = {}) {
  // Prefer server-reported limits; fall back to the local defaults on failure.
  const limits = await getLimits().then((payload) => ({
    ...getStoredLimits(),
    maxUploadBytes: payload.max_upload_bytes,
    maxUploadMb: payload.max_upload_mb,
    allowedExtensions: payload.allowed_extensions,
    minQuestions: payload.min_questions,
    maxQuestions: payload.max_questions,
    defaultQuestions: payload.default_questions,
    quickCounts: payload.quick_counts,
  })).catch(() => getStoredLimits());
  const prefs = getGeneratePrefs();
  const questionTypes = getQuestionTypes();
  const difficulties = getDifficultyLevels();

  // Deep links from the public dashboard (e.g. #/generate?type=case-study)
  // preselect the requested format without persisting it as the default.
  const requestedType = questionTypes.some((type) => type.value === query.type) ? query.type : '';
  if (requestedType) prefs.type = requestedType;

  const content = `
    <div class="page__header page__header--row">
      <div>
        <h1 class="page__title">Generate an assessment</h1>
        <p class="page__subtitle">
          Every question is written from passages retrieved out of your own document, then validated
          before you see it. The answer key stays on the server until you submit.
        </p>
      </div>
    </div>

    <form class="split split--sidebar" id="generate-form" novalidate>
      <div class="card-stack">
        <section class="card">
          <div class="card__header">
            <div>
              <h2 class="card__title">1. Choose your material</h2>
              <p class="card__subtitle">
                ${escapeHtml(limits.allowedExtensions.map((item) => item.toUpperCase()).join(' or '))},
                up to ${escapeHtml(String(limits.maxUploadMb))}MB
              </p>
            </div>
          </div>
          <div class="card__body">
            <div class="dropzone" id="dropzone">
              <span class="dropzone__icon" data-icon-slot="upload"></span>
              <p class="dropzone__title">Drop your document here</p>
              <p class="dropzone__text">or click to browse your files</p>
              <p class="dropzone__hint">Scanned PDFs need OCR before they contain readable text.</p>
            </div>
            <div class="file-chip" id="file-chip" hidden></div>
            <p class="field__error" id="file-error" hidden></p>
            <input type="file" id="file-input" accept="${escapeHtml(limits.allowedExtensions.join(','))}" class="visually-hidden" />
          </div>
        </section>

        <section class="card">
          <div class="card__header">
            <div>
              <h2 class="card__title">2. Question format</h2>
              <p class="card__subtitle">Pick one format or combine several with Mixed</p>
            </div>
          </div>
          <div class="card__body">
            <div class="field">
              <label class="field__label" for="question-type">Question type</label>
              <select class="select" id="question-type" name="type">
                ${questionTypes
                  .map(
                    (type) => `
                  <option value="${escapeHtml(type.value)}" ${type.value === prefs.type ? 'selected' : ''}>
                    ${escapeHtml(type.label)}
                  </option>`,
                  )
                  .join('')}
              </select>
              <p class="field__hint" id="type-hint"></p>
            </div>

            <div class="field" style="margin-top:var(--space-4)">
              <span class="field__label" id="difficulty-label">Difficulty</span>
              <div class="choice-grid" role="radiogroup" aria-labelledby="difficulty-label">
                ${difficulties
                  .map(
                    (level) => `
                  <label class="choice">
                    <input type="radio" name="difficulty" value="${escapeHtml(level.value)}"
                      ${level.value === prefs.difficulty ? 'checked' : ''} />
                    <span class="choice__indicator" aria-hidden="true"></span>
                    <span class="choice__content">
                      <span class="choice__title">${escapeHtml(level.label)}</span>
                      <span class="choice__description">${escapeHtml(DIFFICULTY_HINTS[level.value] || '')}</span>
                    </span>
                  </label>`,
                  )
                  .join('')}
              </div>
            </div>
          </div>
        </section>

        <section class="card">
          <div class="card__header">
            <div>
              <h2 class="card__title">3. Focus and length</h2>
              <p class="card__subtitle">Narrow the retrieval scope and set the question count</p>
            </div>
          </div>
          <div class="card__body" style="display:flex;flex-direction:column;gap:var(--space-4)">
            <div class="field">
              <label class="field__label" for="topic">Topic focus <span class="field__hint">(optional)</span></label>
              <input
                class="input"
                id="topic"
                name="topic"
                type="text"
                maxlength="200"
                placeholder="e.g. Cellular respiration"
                value="${escapeHtml(prefs.topic || '')}"
              />
              <p class="field__hint">Leave blank to cover the whole document.</p>
            </div>

            <div class="field">
              <label class="field__label" for="count">Number of questions</label>
              <div class="tag-row" id="count-chips">
                ${(limits.quickCounts || [5, 10, 15, 20])
                  .map(
                    (count) => `
                  <button type="button" class="btn btn--sm btn--secondary" data-count="${count}">${count}</button>`,
                  )
                  .join('')}
              </div>
              <div style="display:flex;align-items:center;gap:var(--space-3);margin-top:var(--space-2)">
                <input
                  class="input"
                  id="count"
                  name="count"
                  type="number"
                  min="${escapeHtml(String(limits.minQuestions))}"
                  max="${escapeHtml(String(limits.maxQuestions))}"
                  value="${escapeHtml(String(clampCount(prefs.count, limits)))}"
                  style="max-width:140px"
                />
                <span class="field__hint">
                  Between ${escapeHtml(String(limits.minQuestions))} and ${escapeHtml(String(limits.maxQuestions))}
                </span>
              </div>
            </div>

            <div class="field">
              <label class="field__label" for="instructions">Custom instructions <span class="field__hint">(optional)</span></label>
              <textarea
                class="textarea"
                id="instructions"
                name="instructions"
                maxlength="1500"
                placeholder="e.g. Focus on the worked examples and include two application questions."
              >${escapeHtml(prefs.instructions || '')}</textarea>
              <p class="field__hint">Guidance passed straight to the generation step.</p>
            </div>
          </div>
        </section>
      </div>

      <aside class="card-stack" data-rail>
        <section class="card">
          <div class="card__header">
            <h2 class="card__title">Ready to generate</h2>
          </div>
          <div class="card__body" style="display:flex;flex-direction:column;gap:var(--space-4)">
            <dl class="definition-list" style="gap:var(--space-2)">
              <div class="settings-row" style="padding:0;border:none">
                <span class="settings-row__label">Format</span>
                <span class="settings-row__value" id="summary-type"></span>
              </div>
              <div class="settings-row" style="padding:0;border:none">
                <span class="settings-row__label">Questions</span>
                <span class="settings-row__value" id="summary-count"></span>
              </div>
              <div class="settings-row" style="padding:0;border:none">
                <span class="settings-row__label">Difficulty</span>
                <span class="settings-row__value" id="summary-difficulty"></span>
              </div>
            </dl>

            <button type="submit" class="btn btn--primary btn--lg btn--block" id="generate-button">
              <span class="btn__icon" data-icon-slot="sparkle" style="display:flex"></span>
              Generate assessment
            </button>
            <p class="field__hint" style="text-align:center">
              Generation usually takes ${escapeHtml(String(15))}&ndash;${escapeHtml(String(45))} seconds.
            </p>
          </div>
        </section>

        <section class="card" id="progress-card" hidden>
          <div class="card__header">
            <h2 class="card__title">Generating</h2>
          </div>
          <div class="card__body">
            ${stagesMarkup(STAGES)}
            <p class="field__hint" style="margin-top:var(--space-3)">
              Keep this tab open. Retrieving and writing questions both take a moment.
            </p>
          </div>
        </section>

        <section class="card">
          <div class="card__header">
            <h2 class="card__title">What you get</h2>
          </div>
          <div class="card__body">
            <ul class="bullet-list">
              <li class="bullet-list__item">
                <span class="bullet-list__marker">1</span> Questions grounded in retrieved passages
              </li>
              <li class="bullet-list__item">
                <span class="bullet-list__marker">2</span> Automatic grading with per-question explanations
              </li>
              <li class="bullet-list__item">
                <span class="bullet-list__marker">3</span> Partial credit for extended written answers
              </li>
              <li class="bullet-list__item">
                <span class="bullet-list__marker">4</span> Performance analytics from your real attempt history
              </li>
            </ul>
          </div>
        </section>
      </aside>
    </form>`;

  return {
    title: 'Generate Assessment',
    breadcrumb: 'Create from a document',
    content,
    mount(root) {
      hydrateIcons(root, icon);

      let selectedFile = null;
      let inFlight = null;

      const form = root.querySelector('#generate-form');
      const fileInput = root.querySelector('#file-input');
      const typeSelect = root.querySelector('#question-type');
      const countInput = root.querySelector('#count');
      const topicInput = root.querySelector('#topic');
      const instructionsInput = root.querySelector('#instructions');
      const typeHint = root.querySelector('#type-hint');
      const submitButton = root.querySelector('#generate-button');
      const progressCard = root.querySelector('#progress-card');

      const readConfig = () => ({
        type: typeSelect.value,
        count: Number(countInput.value) || limits.defaultQuestions,
        difficulty: form.querySelector('input[name="difficulty"]:checked')?.value || 'medium',
        topic: topicInput.value.trim(),
        instructions: instructionsInput.value.trim(),
      });

      const updateSummary = () => {
        const config = readConfig();
        const label =
          questionTypes.find((type) => type.value === config.type)?.label || titleCase(config.type);
        root.querySelector('#summary-type').textContent = label;
        root.querySelector('#summary-count').textContent = String(config.count);
        root.querySelector('#summary-difficulty').textContent = titleCase(config.difficulty);
        typeHint.textContent = TYPE_HINTS[config.type] || '';
        saveGeneratePrefs(config);
      };

      const unbindDropzone = bindDropzone(root, {
        inputId: 'file-input',
        onSelect(file) {
          if (file === null && fileInput.files?.length) {
            selectedFile = null;
            renderFileSelection(null, limits);
            return;
          }
          if (!file) return;

          const problem = validateFile(file, limits);
          if (problem) {
            toastError(problem);
            selectedFile = null;
            renderFileSelection(null, limits);
            fileInput.value = '';
            return;
          }

          selectedFile = file;
          renderFileSelection(file, limits);
          hydrateIcons(root, icon);
        },
      });

      root.querySelector('#file-chip').addEventListener('click', (event) => {
        if (!event.target.closest('#clear-file')) return;
        selectedFile = null;
        fileInput.value = '';
        renderFileSelection(null, limits);
      });

      typeSelect.addEventListener('change', updateSummary);
      countInput.addEventListener('input', updateSummary);
      topicInput.addEventListener('input', updateSummary);
      instructionsInput.addEventListener('input', updateSummary);
      form.addEventListener('change', updateSummary);

      root.querySelectorAll('[data-count]').forEach((chip) => {
        chip.addEventListener('click', () => {
          countInput.value = chip.dataset.count;
          updateSummary();
        });
      });

      updateSummary();

      const setBusy = (busy) => {
        submitButton.disabled = busy;
        countInput.disabled = busy;
        typeSelect.disabled = busy;
        progressCard.hidden = !busy;
        if (busy) {
          setStageProgress(root, 0);
          root.querySelector('#progress-card').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      };

      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (inFlight) return;

        if (!selectedFile) {
          const problem = validateFile(null, limits);
          toastError(problem);
          root.querySelector('#dropzone').focus();
          return;
        }

        const config = readConfig();
        const clamped = Math.min(limits.maxQuestions, Math.max(limits.minQuestions, config.count));
        if (clamped !== config.count) {
          countInput.value = String(clamped);
          toastError(`Question count must be between ${limits.minQuestions} and ${limits.maxQuestions}.`);
          return;
        }

        setBusy(true);

        // Generous client timeout: generation legitimately takes tens of seconds.
        inFlight = new AbortController();
        const timeout = setTimeout(() => inFlight.abort(), 180000);
        const timer = setInterval(() => {
          const stages = root.querySelectorAll('[data-stage]');
          const active = Array.from(stages).findIndex((stage) => stage.dataset.state === 'active');
          if (active >= 0 && active < STAGES.length - 1) setStageProgress(root, active + 1);
        }, 9000);

        try {
          const quiz = await generateQuiz(
            selectedFile,
            { ...config, count: clamped },
            { signal: inFlight.signal },
          );
          setStageProgress(root, STAGES.length);
          toastSuccess(`Generated ${quiz.question_count || config.count} questions.`);
          window.location.hash = `#/quiz/${encodeURIComponent(quiz.quiz_id)}`;
        } catch (error) {
          setBusy(false);
          if (error.name === 'AbortError') {
            toastError('Generation timed out. Please try again.');
          } else {
            toastError(error.message);
          }
        } finally {
          clearTimeout(timeout);
          clearInterval(timer);
          inFlight = null;
        }
      });

      return () => unbindDropzone();
    },
  };
}

function clampCount(value, limits) {
  const numeric = Number(value) || limits.defaultQuestions;
  return Math.min(limits.maxQuestions, Math.max(limits.minQuestions, numeric));
}