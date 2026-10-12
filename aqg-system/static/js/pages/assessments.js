/**
 * Assessments: every graded attempt with score, timing and drill-down links.
 */

import { listAttempts } from '../api.js';
import {
  debounce,
  escapeHtml,
  formatDateTime,
  formatDuration,
  formatPercent,
  formatRelativeTime,
  hydrateIcons,
  scoreBadge,
} from '../dom.js';
import { icon } from '../icons.js';

const PAGE_SIZE = 15;

export default async function render() {
  let offset = 0;
  let payload = null;
  let loadError = null;

  try {
    payload = await listAttempts({ limit: PAGE_SIZE, offset: 0 });
  } catch (error) {
    loadError = error;
  }

  const attempts = payload?.attempts || [];
  const hasAttempts = attempts.length > 0;

  const content = `
    <div class="page__header page__header--row">
      <div>
        <h1 class="page__title">Assessment attempts</h1>
        <p class="page__subtitle">
          Every submission you have graded, with the exact result the server recorded.
        </p>
      </div>
      <div class="page__actions">
        <a class="btn btn--secondary" href="#/history">
          <span class="btn__icon" data-icon-slot="history" style="display:flex"></span> History
        </a>
        <a class="btn btn--primary" href="#/generate">
          <span class="btn__icon" data-icon-slot="sparkle" style="display:flex"></span> New assessment
        </a>
      </div>
    </div>

    ${
      hasAttempts
        ? `<div class="stat-grid">
             ${summaryTile('award', formatPercent(average(attempts), 0), 'Average score')}
             ${summaryTile('checkCircle', String(best(attempts)), 'Best score')}
             ${summaryTile('clock', formatDuration(averageDuration(attempts)), 'Average time')}
             ${summaryTile('layers', String(totalQuestions(attempts)), 'Questions graded')}
           </div>`
        : ''
    }

    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">All attempts</h2>
          <p class="card__subtitle" id="attempt-count">${escapeHtml(String(payload?.total ?? 0))} recorded</p>
        </div>
      </div>
      <div class="card__body">
        <div class="toolbar-group">
          <label class="visually-hidden" for="attempt-search">Search attempts</label>
          <input class="input" id="attempt-search" type="search" placeholder="Search by topic…" />
        </div>
      </div>
      <div class="card__body card__body--flush" id="attempt-results">
        ${loadError ? renderError(loadError) : renderTable(attempts)}
      </div>
      <div class="pagination">
        <span id="attempt-range"></span>
        <span class="pagination__controls">
          <button type="button" class="btn btn--secondary btn--sm" id="attempt-prev" ${offset <= 0 ? 'disabled' : ''}>
            <span data-icon-slot="chevronLeft" style="display:flex"></span> Previous
          </button>
          <button type="button" class="btn btn--secondary btn--sm" id="attempt-next" disabled>
            Next <span data-icon-slot="chevronRight" style="display:flex"></span>
          </button>
        </span>
      </div>
    </section>`;

  return {
    title: 'Assessment Attempts',
    breadcrumb: 'Every graded submission',
    content,
    mount(root) {
      hydrateIcons(root, icon);

      const results = root.querySelector('#attempt-results');
      const countLabel = root.querySelector('#attempt-count');
      const rangeLabel = root.querySelector('#attempt-range');
      const searchInput = root.querySelector('#attempt-search');
      const prevButton = root.querySelector('#attempt-prev');
      const nextButton = root.querySelector('#attempt-next');

      let currentOffset = 0;
      let inFlight = null;

      const wireRows = () => {
        results.querySelectorAll('[data-attempt-id]').forEach((row) => {
          row.addEventListener('click', (event) => {
            if (event.target.closest('a, button')) return;
            window.location.hash = `#/result/${encodeURIComponent(row.dataset.attemptId)}`;
          });
        });
        results.querySelectorAll('[data-role="retake"]').forEach((button) => {
          button.addEventListener('click', () => {
            window.location.hash = `#/quiz/${encodeURIComponent(button.dataset.quizId)}`;
          });
        });
      };

      const load = async (nextOffset = 0) => {
        if (inFlight) inFlight.abort();
        inFlight = new AbortController();
        results.setAttribute('aria-busy', 'true');
        prevButton.disabled = true;
        nextButton.disabled = true;

        try {
          const data = await listAttempts(
            { limit: PAGE_SIZE, offset: nextOffset },
            { signal: inFlight.signal },
          );

          currentOffset = nextOffset;
          const rows = data.attempts || [];
          results.innerHTML = renderTable(rows);
          hydrateIcons(results, icon);
          wireRows();

          const total = data.total ?? rows.length;
          countLabel.textContent = `${total} recorded`;
          rangeLabel.textContent = total
            ? `Showing ${nextOffset + 1}–${Math.min(nextOffset + PAGE_SIZE, total)} of ${total}`
            : 'Nothing to show';
          prevButton.disabled = nextOffset <= 0;
          nextButton.disabled = nextOffset + PAGE_SIZE >= total;
        } catch (error) {
          if (error.name === 'AbortError') return;
          results.innerHTML = renderError(error);
          hydrateIcons(results, icon);
          rangeLabel.textContent = 'Could not load';
        } finally {
          results.removeAttribute('aria-busy');
          inFlight = null;
        }
      };

      searchInput.addEventListener(
        'input',
        debounce(() => {
          // Client-side filtering keeps typing responsive on large histories.
          const term = searchInput.value.trim().toLowerCase();
          results.querySelectorAll('[data-attempt-id]').forEach((row) => {
            row.hidden = Boolean(term) && !row.textContent.toLowerCase().includes(term);
          });
        }, 200),
      );

      prevButton.addEventListener('click', () => load(Math.max(0, currentOffset - PAGE_SIZE)));
      nextButton.addEventListener('click', () => load(currentOffset + PAGE_SIZE));

      wireRows();
      const total = payload?.total ?? attempts.length;
      rangeLabel.textContent = total
        ? `Showing 1–${Math.min(PAGE_SIZE, total)} of ${total}`
        : 'Nothing to show';
    },
  };
}

function summaryTile(iconName, value, label) {
  return `
    <div class="stat">
      <span class="stat__icon" data-icon-slot="${escapeHtml(iconName)}"></span>
      <div class="stat__body">
        <p class="stat__value">${escapeHtml(value)}</p>
        <p class="stat__label">${escapeHtml(label)}</p>
      </div>
    </div>`;
}

function renderError(error) {
  return `
    <div class="state">
      <span class="state__icon" style="background:var(--danger-50);border-color:var(--danger-200);color:var(--danger-700)">
        <span data-icon-slot="alert" style="display:flex"></span>
      </span>
      <p class="state__title">Attempts could not be loaded</p>
      <p class="state__text">${escapeHtml(error.message)}</p>
      <a class="btn btn--primary" href="#/assessments">Retry</a>
    </div>`;
}

function renderTable(attempts) {
  if (!attempts.length) {
    return `
      <div class="state">
        <span class="state__icon" data-icon-slot="target"></span>
        <p class="state__title">No attempts recorded yet</p>
        <p class="state__text">Generate an assessment, take it, and your graded result will be listed here.</p>
        <a class="btn btn--primary" href="#/generate">Generate an assessment</a>
      </div>`;
  }

  return `
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>Attempt</th>
            <th>Topic</th>
            <th>Score</th>
            <th>Correct</th>
            <th>Time</th>
            <th>Submitted</th>
            <th><span class="visually-hidden">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          ${attempts.map(attemptRow).join('')}
        </tbody>
      </table>
    </div>`;
}

function attemptRow(attempt) {
  return `
    <tr data-attempt-id="${escapeHtml(attempt.attempt_id)}" style="cursor:pointer">
      <td>
        <span class="mono" title="${escapeHtml(attempt.attempt_id)}">${escapeHtml(attempt.attempt_id.slice(0, 8))}</span>
      </td>
      <td>${escapeHtml(attempt.topic || 'Full document')}</td>
      <td class="is-numeric">
        ${scoreBadge(attempt.percentage)}
        <span class="field__hint" style="display:block">${escapeHtml(String(attempt.score))}/${escapeHtml(String(attempt.total_score))}</span>
      </td>
      <td class="is-numeric">${escapeHtml(String(attempt.correct_answers))}/${escapeHtml(String(attempt.total_questions))}</td>
      <td class="is-numeric">${escapeHtml(formatDuration(attempt.time_spent_seconds))}</td>
      <td title="${escapeHtml(formatDateTime(attempt.created_at))}">${escapeHtml(formatRelativeTime(attempt.created_at))}</td>
      <td>
        <span style="display:flex;gap:var(--space-2);justify-content:flex-end">
          <a class="btn btn--soft btn--sm" href="#/result/${encodeURIComponent(attempt.attempt_id)}">Review</a>
          <button type="button" class="btn btn--ghost btn--sm" data-role="retake" data-quiz-id="${escapeHtml(attempt.quiz_id)}">Retake</button>
        </span>
      </td>
    </tr>`;
}

function average(attempts) {
  if (!attempts.length) return 0;
  const total = attempts.reduce((sum, attempt) => sum + (Number(attempt.percentage) || 0), 0);
  return total / attempts.length;
}

function best(attempts) {
  return Math.round(attempts.reduce((top, attempt) => Math.max(top, Number(attempt.percentage) || 0), 0));
}

function averageDuration(attempts) {
  if (!attempts.length) return 0;
  const total = attempts.reduce((sum, attempt) => sum + (Number(attempt.time_spent_seconds) || 0), 0);
  return total / attempts.length;
}

function totalQuestions(attempts) {
  return attempts.reduce((sum, attempt) => sum + (Number(attempt.total_questions) || 0), 0);
}