/**
 * Quiz player: takes an assessment and submits it for automatic grading.
 *
 * The answer key is never present in the payload this page receives, so the
 * learner cannot read answers off the network tab before submitting.
 */

import { getQuiz, submitAssessment } from '../api.js';
import {
  escapeHtml,
  errorState,
  formatDuration,
  hydrateIcons,
  progressBar,
  titleCase,
} from '../dom.js';
import { icon } from '../icons.js';
import {
  answeredCount,
  clearAnswer,
  collectAnswers,
  elapsedSeconds,
  endSession,
  getAnswer,
  getSession,
  hasSession,
  setAnswer,
  startSession,
} from '../store.js';
import { confirmDialog, toastError, toastSuccess } from '../toast.js';

const LONG_FORM_PLACEHOLDER = {
  essay: 'Write a structured answer. Cover the main points from the document and explain your reasoning.',
  application: 'Explain how you would apply this material to the situation described above.',
  'case-study': 'Answer each sub-question in turn, justifying each decision with the document.',
  'short-answer': 'Give a concise answer in your own words.',
  'fill-in-the-blank': 'Type the missing term or phrase.',
};

export default async function render({ params }) {
  const quizId = params.quizId;

  let quiz;
  try {
    quiz = await getQuiz(quizId);
  } catch (error) {
    return {
      title: 'Assessment unavailable',
      content: `<div class="card"><div class="card__body">${errorState({
        title: error.isNotFound ? 'Assessment not found' : 'The assessment could not be loaded',
        text: error.message,
        retryId: 'quiz-retry',
      })}</div></div>`,
      mount(root) {
        hydrateIcons(root, icon);
        root.querySelector('#quiz-retry')?.addEventListener('click', () => {
          window.location.hash = '#/history';
        });
      },
    };
  }

  const questions = quiz.questions || [];
  if (!questions.length) {
    return {
      title: quiz.title || 'Assessment',
      content: `<div class="card"><div class="card__body">${errorState({
        title: 'This assessment has no questions',
        text: 'Regenerate it from the Generate page to get a fresh set.',
        retryId: 'quiz-retry',
      })}</div></div>`,
      mount(root) {
        hydrateIcons(root, icon);
        root.querySelector('#quiz-retry')?.addEventListener('click', () => {
          window.location.hash = '#/generate';
        });
      },
    };
  }

  // Resume the in-progress session for this quiz, otherwise start a new one.
  if (!hasSession(quizId)) startSession(quiz);
  const session = getSession();

  const content = `
    <div class="page__header page__header--row">
      <div>
        <h1 class="page__title">${escapeHtml(quiz.title || quiz.quiz_title || 'Assessment')}</h1>
        <p class="page__subtitle">
          ${escapeHtml(titleCase(quiz.quiz_type || 'mixed'))} &middot;
          ${escapeHtml(titleCase(quiz.difficulty || 'medium'))} &middot;
          ${escapeHtml(String(questions.length))} questions &middot;
          ${escapeHtml(titleCase(quiz.source_filename || 'Uploaded document'))}
        </p>
      </div>
      <div class="page__actions no-print">
        <a class="btn btn--ghost" href="#/history">
          <span class="btn__icon" data-icon-slot="close" style="display:flex"></span> Exit
        </a>
      </div>
    </div>

    ${
      quiz.summary
        ? `<div class="alert alert--info">
             <span class="alert__icon" data-icon-slot="info"></span>
             <div class="alert__body">
               <p class="alert__title">Before you start</p>
               ${escapeHtml(quiz.summary)}
             </div>
           </div>`
        : ''
    }

    <div class="quiz-layout">
      <div class="card-stack" id="question-stack">
        ${questions.map((question, index) => questionCard(question, index, questions.length, session)).join('')}
      </div>

      <aside class="card-stack no-print" data-rail>
        <section class="card">
          <div class="card__header">
            <h2 class="card__title">Progress</h2>
          </div>
          <div class="card__body" style="display:flex;flex-direction:column;gap:var(--space-4)">
            <div>
              <p class="stat__value" id="progress-value">0/${questions.length}</p>
              <p class="stat__label">Questions answered</p>
            </div>
            ${progressBar(0)}
            <div class="qnav" id="qnav">
              ${questions
                .map(
                  (question) =>
                    `<a class="qnav__dot" href="#question-${question.id}" data-dotnet="${question.id}" data-answered="false">${question.id}</a>`,
                )
                .join('')}
            </div>
            <p class="field__hint" id="time-elapsed">Elapsed 0s</p>
          </div>
          <div class="card__footer">
            <button type="button" class="btn btn--primary btn--block" id="submit-quiz">
              <span class="btn__icon" data-icon-slot="check" style="display:flex"></span> Submit for grading
            </button>
          </div>
        </section>

        <section class="card">
          <div class="card__header">
            <h2 class="card__title">Instructions</h2>
          </div>
          <div class="card__body">
            <ul class="bullet-list">
              <li class="bullet-list__item">
                <span class="bullet-list__marker"><span data-icon-slot="shield" style="display:flex"></span></span>
                Answers are revealed only after you submit.
              </li>
              <li class="bullet-list__item">
                <span class="bullet-list__marker"><span data-icon-slot="clock" style="display:flex"></span></span>
                Leave a question blank if you are unsure; it is marked unanswered.
              </li>
              <li class="bullet-list__item">
                <span class="bullet-list__marker"><span data-icon-slot="scale" style="display:flex"></span></span>
                Written answers earn partial credit based on how much of the key points you cover.
              </li>
            </ul>
          </div>
        </section>
      </aside>
    </div>`;

  return {
    title: quiz.title || 'Take Assessment',
    breadcrumb: quiz.topic || 'Assessment in progress',
    content,
    mount(root) {
      hydrateIcons(root, icon);

      const progressValue = root.querySelector('#progress-value');
      const progressBarEl = root.querySelector('.progress__bar');
      const submitButton = root.querySelector('#submit-quiz');
      const timeLabel = root.querySelector('#time-elapsed');
      const dots = Array.from(root.querySelectorAll('[data-dotnet]'));
      let submitting = false;

      const syncProgress = () => {
        const answered = answeredCount();
        progressValue.textContent = `${answered}/${questions.length}`;
        progressBarEl.style.width = `${(answered / questions.length) * 100}%`;

        dots.forEach((dot) => {
          const value = session.answers.get(Number(dot.dataset.dotnet));
          dot.dataset.answered = value && String(value).trim() ? 'true' : 'false';
        });

        if (submitButton) {
          const remaining = questions.length - answered;
          submitButton.textContent = remaining
            ? `Submit with ${remaining} unanswered`
            : 'Submit for grading';
          if (submitButton.dataset.ready === undefined) {
            submitButton.dataset.ready = 'true';
            submitButton.insertAdjacentHTML('afterbegin', icon('check', { size: 18 }));
          }
        }
      };

      // Restore any answers already captured for this quiz.
      questions.forEach((question) => {
        applyAnswer(root, question.id, getAnswer(question.id));
      });
      syncProgress();

      const timer = setInterval(() => {
        if (timeLabel) timeLabel.textContent = `Elapsed ${formatDuration(elapsedSeconds())}`;
      }, 1000);

      root.addEventListener('change', (event) => {
        const input = event.target.closest('[data-answer-for]');
        if (!input) return;
        const questionId = Number(input.dataset.answerFor);

        if (input.dataset.kind === 'text') {
          setAnswer(questionId, input.value);
        } else if (input.checked) {
          setAnswer(questionId, input.value);
        } else {
          clearAnswer(questionId);
        }
        syncProgress();
      });

      root.querySelectorAll('[data-hint-for]').forEach((button) => {
        button.addEventListener('click', () => {
          const hint = root.querySelector(`#hint-${button.dataset.hintFor}`);
          if (!hint) return;
          hint.hidden = !hint.hidden;
          button.textContent = hint.hidden ? 'Show hint' : 'Hide hint';
        });
      });

      submitButton.addEventListener('click', async () => {
        if (submitting) return;

        const answered = answeredCount();
        if (!answered) {
          toastError('Please answer at least one question before submitting.');
          return;
        }

        const unanswered = questions.length - answered;
        const confirmed = await confirmDialog({
          title: unanswered ? `Submit with ${unanswered} unanswered?` : 'Submit for grading?',
          text: unanswered
            ? 'Unanswered questions are marked as unanswered. You cannot change your answers afterwards.'
            : 'Your answers will be graded automatically. You cannot change them afterwards.',
          confirmLabel: 'Submit',
          tone: 'primary',
        });
        if (!confirmed) return;

        submitting = true;
        submitButton.disabled = true;
        submitButton.innerHTML = `<span class="spinner" style="width:18px;height:18px"></span> Grading…`;

        try {
          const payload = await submitAssessment(quizId, {
            answers: collectAnswers(),
            time_spent_seconds: elapsedSeconds(),
          });
          const result = payload.result;
          endSession();
          toastSuccess('Assessment graded.');
          window.location.hash = `#/result/${encodeURIComponent(result.attempt_id)}`;
        } catch (error) {
          submitting = false;
          submitButton.disabled = false;
          submitButton.textContent = 'Submit for grading';
          submitButton.insertAdjacentHTML('afterbegin', icon('check', { size: 18 }));
          toastError(error.message);
        }
      });

      return () => clearInterval(timer);
    },
  };
}

function questionCard(question, index, total, session) {
  const isChoice = (question.options || []).length > 0;
  const type = question.type || 'short-answer';
  const saved = session.answers.get(question.id) ?? '';
  const scenario = question.scenario || (type === 'case-study' ? question.case_description : '');

  return `
    <article class="card quiz-card" id="question-${escapeHtml(String(question.id))}">
      <div class="quiz-card__top">
        <span class="quiz-card__number">
          <span data-icon-slot="layers" style="display:flex"></span>
          Question ${escapeHtml(String(question.id))} of ${escapeHtml(String(total))}
        </span>
        <span class="quiz-card__badges">
          <span class="badge badge--brand">${escapeHtml(titleCase(type))}</span>
          <span class="badge badge--neutral">${escapeHtml(titleCase(question.difficulty || 'medium'))}</span>
          ${question.points ? `<span class="badge badge--info">${escapeHtml(String(question.points))} pts</span>` : ''}
          ${question.topic ? `<span class="badge badge--neutral">${escapeHtml(question.topic)}</span>` : ''}
        </span>
      </div>

      ${
        scenario
          ? `<div class="scenario-block">
               <p class="scenario-block__label">${type === 'case-study' ? 'Case study' : 'Scenario'}</p>
               <p class="scenario-block__text">${escapeHtml(scenario)}</p>
             </div>`
          : ''
      }

      <p class="quiz-card__prompt">${escapeHtml(question.question)}</p>

      ${
        isChoice
          ? `<div class="answer-list">
               ${question.options
                 .map(
                   (option) => `
                 <label class="answer-option">
                   <input type="radio" name="q-${escapeHtml(String(question.id))}"
                     data-answer-for="${escapeHtml(String(question.id))}" data-kind="choice"
                     value="${escapeHtml(option.text)}"
                     ${saved === option.text ? 'checked' : ''} />
                   <span class="answer-option__label">${escapeHtml(option.id || '?')}</span>
                   <span class="answer-option__text">${escapeHtml(option.text)}</span>
                 </label>`,
                 )
                 .join('')}
             </div>`
          : `<div class="field">
               <label class="field__label visually-hidden" for="text-${escapeHtml(String(question.id))}">
                 Your answer to question ${escapeHtml(String(question.id))}
               </label>
               <textarea
                 class="textarea"
                 id="text-${escapeHtml(String(question.id))}"
                 data-answer-for="${escapeHtml(String(question.id))}" data-kind="text"
                 rows="${type === 'short-answer' || type === 'fill-in-the-blank' ? 2 : 6}"
                 placeholder="${escapeHtml(LONG_FORM_PLACEHOLDER[type] || 'Type your answer…')}"
               >${escapeHtml(saved)}</textarea>
             </div>`
      }

      ${
        question.hint
          ? `<div>
               <button type="button" class="btn btn--ghost btn--sm" data-hint-for="${escapeHtml(String(question.id))}">
                 <span data-icon-slot="bulb" style="display:flex"></span> Show hint
               </button>
               <p class="explanation" id="hint-${escapeHtml(String(question.id))}" hidden>${escapeHtml(question.hint)}</p>
             </div>`
          : ''
      }
    </article>`;
}

function applyAnswer(root, questionId, value) {
  const safeValue = String(value ?? '');
  if (!safeValue) return;

  const textarea = root.querySelector(`[data-answer-for="${questionId}"][data-kind="text"]`);
  if (textarea) {
    textarea.value = safeValue;
    return;
  }

  const radios = Array.from(
    root.querySelectorAll(`input[type="radio"][data-answer-for="${questionId}"]`),
  );
  const match = radios.find((radio) => radio.value === safeValue);
  if (match) match.checked = true;
}