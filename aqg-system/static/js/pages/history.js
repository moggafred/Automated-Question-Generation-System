/**
 * History: browse, search, reopen and delete saved assessments.
 */

import { deleteQuiz, listQuizzes } from '../api.js';
import {
  debounce,
  escapeHtml,
  formatDateTime,
  formatRelativeTime,
  hydrateIcons,
  scoreBadge,
  titleCase,
} from '../dom.js';
import { icon } from '../icons.js';
import { getQuestionTypes } from '../store.js';
import { confirmDialog, toastError, toastSuccess } from '../toast.js';

const PAGE_SIZE = 12;

export default async function render({ query }) {
  const topics = [];
  const types = getQuestionTypes();

  let offset = Number(query.offset) || 0;
  let payload = null;
  let loadError = null;

  try {
    payload = await listQuizzes({
      limit: PAGE_SIZE,
      offset,
      topic: query.topic || '',
      type: query.type || '',
      search: query.search || '',
    });
  } catch (error) {
    loadError = error;
  }

  const quizzes = payload?.quizzes || [];

  const content = `
    <div class="page__header page__header--row">
      <div>
        <h1 class="page__title">Assessment history</h1>
        <p class="page__subtitle">
          Every assessment you have generated. Reopen one to retake it or review how it performed.
        </p>
      </div>
      <div class="page__actions">
        <a class="btn btn--primary" href="#/generate">
          <span class="btn__icon" data-icon-slot="sparkle" style="display:flex"></span> New assessment
        </a>
      </div>
    </div>

    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">Saved assessments</h2>
          <p class="card__subtitle" id="history-count">${escapeHtml(String(payload?.filtered ?? payload?.total ?? 0))} match(es)</p>
        </div>
      </div>
      <div class="card__body">
        <div class="toolbar-group">
          <label class="visually-hidden" for="history-search">Search assessments</label>
          <input
            class="input"
            id="history-search"
            type="search"
            placeholder="Search topic, title or filename…"
            value="${escapeHtml(query.search || '')}"
          />
          <label class="visually-hidden" for="history-type">Filter by question type</label>
          <select class="select" id="history-type">
            <option value="">All question types</option>
            ${types
              .map(
                (type) => `
              <option value="${escapeHtml(type.value)}" ${query.type === type.value ? 'selected' : ''}>
                ${escapeHtml(type.label)}
              </option>`,
              )
              .join('')}
          </select>
          <label class="visually-hidden" for="history-topic">Filter by topic</label>
          <select class="select" id="history-topic">
            <option value="">All topics</option>
            ${(payload?.topics || topics)
              .map(
                (topic) => `
              <option value="${escapeHtml(topic)}" ${query.topic === topic ? 'selected' : ''}>
                ${escapeHtml(topic)}
              </option>`,
              )
              .join('')}
          </select>
        </div>
      </div>
      <div class="card__body card__body--flush" id="history-results">
        ${loadError ? renderError(loadError) : renderRows(quizzes)}
      </div>
      <div class="pagination">
        <span id="history-range"></span>
        <span class="pagination__controls">
          <button type="button" class="btn btn--secondary btn--sm" id="history-prev" ${offset <= 0 ? 'disabled' : ''}>
            <span data-icon-slot="chevronLeft" style="display:flex"></span> Previous
          </button>
          <button type="button" class="btn btn--secondary btn--sm" id="history-next" ${offset + PAGE_SIZE >= (payload?.filtered ?? 0) ? 'disabled' : ''}>
            Next <span data-icon-slot="chevronRight" style="display:flex"></span>
          </button>
        </span>
      </div>
    </section>`;

  return {
    title: 'History',
    breadcrumb: 'Your saved assessments',
    content,
    mount(root) {
      hydrateIcons(root, icon);

      const results = root.querySelector('#history-results');
      const countLabel = root.querySelector('#history-count');
      const rangeLabel = root.querySelector('#history-range');
      const searchInput = root.querySelector('#history-search');
      const typeSelect = root.querySelector('#history-type');
      const topicSelect = root.querySelector('#history-topic');
      const prevButton = root.querySelector('#history-prev');
      const nextButton = root.querySelector('#history-next');

      let currentOffset = offset;
      let inFlight = null;

      const syncUrl = (nextOffset) => {
        const suffix = buildQuery({
          search: searchInput.value.trim(),
          type: typeSelect.value,
          topic: topicSelect.value,
          offset: nextOffset || undefined,
        });
        window.history.replaceState(null, '', `#/history${suffix}`);
      };

      const onDelete = async (id) => {
        const confirmed = await confirmDialog({
          title: 'Delete this assessment?',
          text: 'The assessment and its recorded attempts will be removed permanently.',
          confirmLabel: 'Delete',
        });
        if (!confirmed) return;

        try {
          await deleteQuiz(id);
          toastSuccess('Assessment deleted.');
          await loadResults(currentOffset);
        } catch (error) {
          toastError(error.message);
        }
      };

      const wireRows = () => {
        results.querySelectorAll('[data-role="delete"]').forEach((button) => {
          button.addEventListener('click', () => onDelete(button.dataset.id));
        });
        results.querySelectorAll('[data-role="open"]').forEach((button) => {
          button.addEventListener('click', () => {
            window.location.hash = `#/quiz/${encodeURIComponent(button.dataset.id)}`;
          });
        });
      };

      const loadResults = async (nextOffset = 0) => {
        if (inFlight) inFlight.abort();
        inFlight = new AbortController();

        results.setAttribute('aria-busy', 'true');
        prevButton.disabled = true;
        nextButton.disabled = true;

        try {
          const data = await listQuizzes(
            {
              limit: PAGE_SIZE,
              offset: nextOffset,
              topic: topicSelect.value,
              type: typeSelect.value,
              search: searchInput.value.trim(),
            },
            { signal: inFlight.signal },
          );

          currentOffset = nextOffset;
          results.innerHTML = renderRows(data.quizzes || []);
          hydrateIcons(results, icon);
          wireRows();

          const total = data.filtered ?? data.total ?? 0;
          countLabel.textContent = `${total} match(es)`;
          rangeLabel.textContent = total
            ? `Showing ${nextOffset + 1}–${Math.min(nextOffset + PAGE_SIZE, total)} of ${total}`
            : 'Nothing to show';
          prevButton.disabled = nextOffset <= 0;
          nextButton.disabled = nextOffset + PAGE_SIZE >= total;
          syncUrl(nextOffset);
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

      const pushSearch = debounce(() => loadResults(0), 350);
      searchInput.addEventListener('input', pushSearch);
      typeSelect.addEventListener('change', () => loadResults(0));
      topicSelect.addEventListener('change', () => loadResults(0));
      prevButton.addEventListener('click', () => loadResults(Math.max(0, currentOffset - PAGE_SIZE)));
      nextButton.addEventListener('click', () => loadResults(currentOffset + PAGE_SIZE));

      wireRows();
      if (payload) {
        const total = payload.filtered ?? payload.total ?? 0;
        rangeLabel.textContent = total
          ? `Showing ${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total}`
          : 'Nothing to show';
      }
    },
  };
}

function buildQuery(values) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === null || value === '') continue;
    search.set(key, String(value));
  }
  const serialized = search.toString();
  return serialized ? `?${serialized}` : '';
}

function renderError(error) {
  return `
    <div class="state">
      <span class="state__icon" style="background:var(--danger-50);border-color:var(--danger-200);color:var(--danger-700)">
        <span data-icon-slot="alert" style="display:flex"></span>
      </span>
      <p class="state__title">History could not be loaded</p>
      <p class="state__text">${escapeHtml(error.message)}</p>
      <a class="btn btn--primary" href="#/history">Retry</a>
    </div>`;
}

function renderRows(quizzes) {
  if (!quizzes.length) {
    return `
      <div class="state">
        <span class="state__icon" data-icon-slot="history"></span>
        <p class="state__title">No assessments found</p>
        <p class="state__text">Generate an assessment from a document and it will appear here automatically.</p>
        <a class="btn btn--primary" href="#/generate">Generate one now</a>
      </div>`;
  }

  return `<div class="record-list">${quizzes.map(quizRow).join('')}</div>`;
}

function quizRow(quiz) {
  const attempts = Number(quiz.attempt_count) || 0;
  return `
    <div class="activity-item">
      <span class="activity-item__icon" data-kind="assessment" data-icon-slot="quiz"></span>
      <span class="activity-item__body">
        <span class="activity-item__title">${escapeHtml(quiz.quiz_title || 'Generated Assessment')}</span>
        <span class="activity-item__meta">
          <span class="badge badge--brand">${escapeHtml(quiz.quiz_type_label || titleCase(quiz.quiz_type))}</span>
          <span class="badge badge--neutral">${escapeHtml(titleCase(quiz.difficulty || 'medium'))}</span>
          <span>${escapeHtml(String(quiz.num_questions || quiz.question_count || 0))} questions</span>
          <span>&middot;</span>
          <span title="${escapeHtml(formatDateTime(quiz.created_at))}">${escapeHtml(formatRelativeTime(quiz.created_at))}</span>
        </span>
        <span class="activity-item__meta">
          <span title="${escapeHtml(quiz.source_filename || '')}">
            <span data-icon-slot="fileText" style="display:inline-flex;vertical-align:-3px"></span>
            ${escapeHtml(quiz.source_filename || 'Uploaded document')}
          </span>
          <span>&middot;</span>
          <span>${escapeHtml(quiz.topic || 'Full document')}</span>
          <span>&middot;</span>
          <span>${escapeHtml(String(attempts))} attempt(s)</span>
        </span>
      </span>
      ${
        quiz.best_percentage !== null && quiz.best_percentage !== undefined
          ? scoreBadge(quiz.best_percentage)
          : '<span class="badge badge--neutral">Not attempted</span>'
      }
      <span class="no-print" style="display:flex;gap:var(--space-2)">
        <button type="button" class="btn btn--soft btn--sm" data-role="open" data-id="${escapeHtml(quiz.quiz_id)}">
          Open
        </button>
        <button type="button" class="btn btn--ghost btn--icon-only" data-role="delete" data-id="${escapeHtml(quiz.quiz_id)}" aria-label="Delete assessment">
          <span data-icon-slot="trash" style="display:flex"></span>
        </button>
      </span>
    </div>`;
}