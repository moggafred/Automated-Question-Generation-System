/**
 * Result: graded outcome for one attempt, including per-question feedback.
 *
 * This is the only screen that reveals the answer key, and only because the
 * server has already graded the submission.
 */

import { getAttempt, getQuiz } from '../api.js';
import { scoreRing } from '../charts.js';
import {
  escapeHtml,
  errorState,
  formatDuration,
  formatPercent,
  hydrateIcons,
  titleCase,
  toneForScore,
} from '../dom.js';
import { icon } from '../icons.js';
import { clearLastResult, getLastResult } from '../store.js';
import { toastError } from '../toast.js';

const BAND_VERDICTS = {
  excellent: 'Outstanding mastery of this material.',
  'very-good': 'Very Good — a strong grasp with a few gaps to review.',
  good: 'Good — solid understanding, revisit the missed topics.',
  satisfactory: 'Satisfactory — review the material and retake for a better result.',
  'needs-improvement': 'Needs Improvement — work through the study materials again.',
  unsatisfactory: 'Unsatisfactory — rebuild the fundamentals before moving on.',
};

export default async function render({ params }) {
  const attemptId = params.attemptId;
  const cached = getLastResult();

  let attempt = null;
  let review = [];
  let answers = [];
  let band = null;
  let error = null;

  if (cached?.attempt_id === attemptId) {
    attempt = cached;
    review = cached.review || [];
    band = cached.performance_band;
  } else {
    try {
      const payload = await getAttempt(attemptId);
      attempt = payload.attempt;
      review = payload.review || [];
      answers = payload.answers || [];
      band = payload.performance_band;
    } catch (requestError) {
      error = requestError;
    }
  }

  if (error) {
    return {
      title: 'Result unavailable',
      content: `<div class="card"><div class="card__body">${errorState({
        title: error.isNotFound ? 'Result not found' : 'The result could not be loaded',
        text: error.message,
        retryId: 'result-retry',
      })}</div></div>`,
      mount(root) {
        hydrateIcons(root, icon);
        root.querySelector('#result-retry')?.addEventListener('click', () => {
          window.location.hash = '#/assessments';
        });
      },
    };
  }

  if (!attempt) {
    return {
      title: 'Result unavailable',
      content: `<div class="card"><div class="card__body">${errorState({
        title: 'Nothing to show',
        text: 'We could not find that attempt.',
      })}</div></div>`,
      mount(root) {
        hydrateIcons(root, icon);
      },
    };
  }

  const percentage = Number(attempt.percentage) || 0;
  const bandLabel = titleCase(band || 'graded');
  const breakdown = attempt.breakdown || {};

  const content = `
    <div class="page__header page__header--row">
      <div>
        <h1 class="page__title">${escapeHtml(attempt.quiz_title || 'Assessment result')}</h1>
        <p class="page__subtitle">
          ${escapeHtml(attempt.topic || 'Full document')} &middot;
          submitted ${escapeHtml(formatDuration(attempt.time_spent_seconds))} of work
        </p>
      </div>
      <div class="page__actions no-print">
        <button type="button" class="btn btn--secondary" id="print-result">
          <span class="btn__icon" data-icon-slot="print" style="display:flex"></span> Print
        </button>
        <a class="btn btn--secondary" href="#/study">
          <span class="btn__icon" data-icon-slot="book" style="display:flex"></span> Study this topic
        </a>
        <a class="btn btn--primary" href="#/quiz/${encodeURIComponent(attempt.quiz_id)}">
          <span class="btn__icon" data-icon-slot="refresh" style="display:flex"></span> Retake
        </a>
      </div>
    </div>

    <section class="card">
      <div class="score-hero">
        ${scoreRing(percentage)}
        <div class="score-summary">
          <p class="score-summary__band">${escapeHtml(bandLabel)}</p>
          <p class="score-summary__text">
            ${escapeHtml(BAND_VERDICTS[band] || 'Your submission has been graded automatically.')}
          </p>
        </div>
        <div class="score-breakdown">
          ${breakdownTile(`${escapeHtml(String(attempt.score))}/${escapeHtml(String(attempt.total_score))}`, 'Marks', '')}
          ${breakdownTile(String(attempt.correct_answers ?? 0), 'Fully correct', 'success')}
          ${breakdownTile(String(attempt.incorrect_answers ?? 0), 'Incorrect', 'danger')}
          ${breakdownTile(String(attempt.unanswered ?? 0), 'Unanswered', 'warning')}
        </div>
      </div>
    </section>

    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">How you did by question type</h2>
          <p class="card__subtitle">Average score per format, from your submission</p>
        </div>
      </div>
      <div class="card__body">
        ${
          Object.keys(breakdown).length
            ? `<div class="bar-list">
                 ${Object.entries(breakdown)
                   .map(([type, values]) => {
                     const average = Number(values?.average_percentage ?? values?.average ?? 0);
                     return `
                       <div class="bar-row">
                         <div class="bar-row__head">
                           <span class="bar-row__label">${escapeHtml(titleCase(type))}</span>
                           <span class="bar-row__value">${escapeHtml(formatPercent(average, 0))}</span>
                         </div>
                         <div class="progress" role="progressbar" aria-valuenow="${Math.round(average)}" aria-valuemin="0" aria-valuemax="100">
                           <div class="progress__bar" data-tone="${escapeHtml(toneForScore(average))}" style="width:${Math.round(average)}%"></div>
                         </div>
                       </div>`;
                   })
                   .join('')}
               </div>`
            : `<p class="field__hint">No per-type breakdown was recorded for this attempt.</p>`
        }
      </div>
    </section>

    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">Question by question</h2>
          <p class="card__subtitle">
            ${escapeHtml(String(review.length))} item(s) &middot;
            ${escapeHtml(String(attempt.attempted ?? attempt.total_questions ?? review.length))} attempted
          </p>
        </div>
      </div>
      <div class="card__body card__body--flush">
        ${
          review.length
            ? review.map(reviewItem).join('')
            : `<div class="state"><p class="state__title">No review available</p></div>`
        }
      </div>
    </section>

    ${
      answers.length
        ? `<section class="card">
             <div class="card__header"><h2 class="card__title">Your submitted answers</h2></div>
             <div class="card__body card__body--flush">
               <div class="table-wrap">
                 <table class="data-table">
                   <thead>
                     <tr><th>Question</th><th>Your answer</th></tr>
                   </thead>
                   <tbody>
                     ${answers
                       .map(
                         (answer) => `
                       <tr>
                         <td class="is-numeric">${escapeHtml(String(answer.question_id ?? ''))}</td>
                         <td>${escapeHtml(answer.answer || 'Not answered')}</td>
                       </tr>`,
                       )
                       .join('')}
                   </tbody>
                 </table>
               </div>
             </div>
           </section>`
        : ''
    }`;

  return {
    title: 'Assessment Result',
    breadcrumb: bandLabel,
    content,
    mount(root) {
      hydrateIcons(root, icon);

      const fraction = root.querySelector('[data-role="fraction"]');
      if (fraction) {
        fraction.textContent = `${attempt.score ?? 0} / ${attempt.total_score ?? 0} marks`;
      }

      root.querySelector('#print-result')?.addEventListener('click', () => window.print());

      const retake = root.querySelector('a.btn--primary');
      retake?.addEventListener('click', async (event) => {
        event.preventDefault();
        clearLastResult();
        try {
          await getQuiz(attempt.quiz_id);
          window.location.hash = `#/quiz/${encodeURIComponent(attempt.quiz_id)}`;
        } catch (requestError) {
          toastError(requestError.message);
        }
      });
    },
  };
}

function breakdownTile(value, label, tone) {
  const toneAttr = tone ? ` data-tone="${escapeHtml(tone)}"` : '';
  return `
    <div class="score-breakdown__item"${toneAttr}>
      <p class="score-breakdown__value">${value}</p>
      <p class="score-breakdown__label">${escapeHtml(label)}</p>
    </div>`;
}

function reviewItem(item) {
  const verdict = item.correct ? 'correct' : item.partial ? 'partial' : item.your_answer ? 'wrong' : 'empty';
  const verdictLabel = item.correct ? 'Correct' : item.partial ? 'Partial credit' : item.your_answer ? 'Incorrect' : 'Not answered';
  const scenario = item.scenario;

  return `
    <article class="review-item">
      <div class="review-item__head">
        <span class="quiz-card__number">
          <span data-icon-slot="${item.correct ? 'checkCircle' : item.partial ? 'minus' : 'xCircle'}" style="display:flex"></span>
          Question ${escapeHtml(String(item.question_id))}
        </span>
        <span class="quiz-card__badges">
          <span class="badge badge--${verdict === 'correct' ? 'success' : verdict === 'partial' ? 'warning' : verdict === 'wrong' ? 'danger' : 'neutral'}">
            ${escapeHtml(verdictLabel)}
          </span>
          <span class="badge badge--brand">${escapeHtml(titleCase(item.type))}</span>
          ${item.auto_graded === false ? '<span class="badge badge--neutral">Needs review</span>' : ''}
        </span>
      </div>

      ${
        scenario
          ? `<div class="scenario-block">
               <p class="scenario-block__label">Scenario</p>
               <p class="scenario-block__text">${escapeHtml(scenario)}</p>
             </div>`
          : ''
      }

      <p class="review-item__prompt">${escapeHtml(item.question)}</p>

      <div class="review-item__answers">
        <div class="review-answer review-answer--${verdict}">
          <span class="review-answer__label">Your answer</span>
          ${escapeHtml(item.your_answer || 'You left this blank.')}
        </div>
        <div class="review-answer review-answer--correct">
          <span class="review-answer__label">Correct answer</span>
          ${escapeHtml(item.correct_answer)}
        </div>
      </div>

      ${
        item.explanation
          ? `<div class="explanation">
               <strong>Why:</strong> ${escapeHtml(item.explanation)}
             </div>`
          : ''
      }

      ${
        item.marking_criteria?.length
          ? `<div>
               <p class="prose-block__title" style="margin-bottom:var(--space-2)">
                 <span data-icon-slot="scale" style="display:flex"></span> Marking guidance
               </p>
               <div class="marking-list">
                 ${item.marking_criteria
                   .map(
                     (criterion) => `
                   <span class="marking-list__item">
                     <span class="marking-list__bullet">${icon('check', { size: 10 })}</span>
                     ${escapeHtml(criterion)}
                   </span>`,
                   )
                   .join('')}
               </div>
             </div>`
          : ''
      }

      ${
        item.source_reference
          ? `<p class="field__hint">
               <span data-icon-slot="fileText" style="display:inline-flex;vertical-align:-3px"></span>
               Source: ${escapeHtml(item.source_reference)}
             </p>`
          : ''
      }
    </article>`;
}