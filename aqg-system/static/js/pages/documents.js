/**
 * Documents: everything uploaded and indexed, with the metrics captured at ingest.
 */

import { listDocuments } from '../api.js';
import {
  escapeHtml,
  formatBytes,
  formatDateTime,
  formatNumber,
  formatRelativeTime,
  hydrateIcons,
} from '../dom.js';
import { icon } from '../icons.js';

const PAGE_SIZE = 15;

const STATUS_TONES = {
  processed: 'success',
  completed: 'success',
  ready: 'success',
  failed: 'danger',
  error: 'danger',
  pending: 'warning',
};

export default async function render() {
  let offset = 0;
  let payload = null;
  let loadError = null;

  try {
    payload = await listDocuments({ limit: PAGE_SIZE, offset: 0 });
  } catch (error) {
    loadError = error;
  }

  const documents = payload?.documents || [];
  const limits = payload?.limits || {};

  const content = `
    <div class="page__header page__header--row">
      <div>
        <h1 class="page__title">Documents</h1>
        <p class="page__subtitle">
          Every file you have processed, with the page, word and chunk counts recorded when it was
          first indexed.
        </p>
      </div>
      <div class="page__actions">
        <a class="btn btn--primary" href="#/generate">
          <span class="btn__icon" data-icon-slot="upload" style="display:flex"></span> Upload a document
        </a>
      </div>
    </div>

    ${
      limits.max_upload_mb
        ? `<div class="alert alert--info">
             <span class="alert__icon" data-icon-slot="info"></span>
             <div class="alert__body">
               Accepted formats: ${escapeHtml((limits.allowed_extensions || []).map((item) => item.toUpperCase()).join(', '))}
               &middot; maximum ${escapeHtml(String(limits.max_upload_mb))}MB per file.
             </div>
           </div>`
        : ''
    }

    ${
      documents.length
        ? `<div class="stat-grid">
             ${tile('file', formatNumber(payload.total), 'Documents indexed')}
             ${tile('layers', formatNumber(sum(documents, 'chunk_count')), 'Chunks indexed')}
             ${tile('book', formatNumber(sum(documents, 'word_count')), 'Words extracted')}
             ${tile('fileText', formatNumber(sum(documents, 'page_count')), 'Pages read')}
           </div>`
        : ''
    }

    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">Indexed documents</h2>
          <p class="card__subtitle" id="document-count">${escapeHtml(String(payload?.total ?? 0))} stored</p>
        </div>
      </div>
      <div class="card__body card__body--flush" id="document-results">
        ${loadError ? renderError(loadError) : renderTable(documents)}
      </div>
      <div class="pagination">
        <span id="document-range"></span>
        <span class="pagination__controls">
          <button type="button" class="btn btn--secondary btn--sm" id="document-prev" ${offset <= 0 ? 'disabled' : ''}>
            <span data-icon-slot="chevronLeft" style="display:flex"></span> Previous
          </button>
          <button type="button" class="btn btn--secondary btn--sm" id="document-next" disabled>
            Next <span data-icon-slot="chevronRight" style="display:flex"></span>
          </button>
        </span>
      </div>
    </section>`;

  return {
    title: 'Documents',
    breadcrumb: 'Everything you have processed',
    content,
    mount(root) {
      hydrateIcons(root, icon);

      const results = root.querySelector('#document-results');
      const countLabel = root.querySelector('#document-count');
      const rangeLabel = root.querySelector('#document-range');
      const prevButton = root.querySelector('#document-prev');
      const nextButton = root.querySelector('#document-next');

      let currentOffset = 0;
      let inFlight = null;

      const load = async (nextOffset = 0) => {
        if (inFlight) inFlight.abort();
        inFlight = new AbortController();
        results.setAttribute('aria-busy', 'true');
        prevButton.disabled = true;
        nextButton.disabled = true;

        try {
          const data = await listDocuments(
            { limit: PAGE_SIZE, offset: nextOffset },
            { signal: inFlight.signal },
          );

          currentOffset = nextOffset;
          results.innerHTML = renderTable(data.documents || []);
          hydrateIcons(results, icon);

          const total = data.total ?? 0;
          countLabel.textContent = `${total} stored`;
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

      prevButton.addEventListener('click', () => load(Math.max(0, currentOffset - PAGE_SIZE)));
      nextButton.addEventListener('click', () => load(currentOffset + PAGE_SIZE));

      const total = payload?.total ?? documents.length;
      rangeLabel.textContent = total
        ? `Showing 1–${Math.min(PAGE_SIZE, total)} of ${total}`
        : 'Nothing to show';
    },
  };
}

function tile(iconName, value, label) {
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
      <p class="state__title">Documents could not be loaded</p>
      <p class="state__text">${escapeHtml(error.message)}</p>
      <a class="btn btn--primary" href="#/documents">Retry</a>
    </div>`;
}

function renderTable(documents) {
  if (!documents.length) {
    return `
      <div class="state">
        <span class="state__icon" data-icon-slot="file"></span>
        <p class="state__title">No documents yet</p>
        <p class="state__text">Upload a PDF or TXT learning material from the Generate page and it will be indexed here.</p>
        <a class="btn btn--primary" href="#/generate">Upload a document</a>
      </div>`;
  }

  return `
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>File</th>
            <th>Pages</th>
            <th>Words</th>
            <th>Chunks</th>
            <th>Size</th>
            <th>Status</th>
            <th>Indexed</th>
          </tr>
        </thead>
        <tbody>
          ${documents
            .map(
              (document) => `
            <tr>
              <td>
                <span style="display:flex;align-items:center;gap:var(--space-2)">
                  <span data-icon-slot="${document.extension === '.pdf' ? 'fileText' : 'file'}" style="color:var(--text-tertiary);flex-shrink:0"></span>
                  <span>
                    <strong>${escapeHtml(document.filename)}</strong>
                    <span class="field__hint" style="display:block" title="${escapeHtml(document.document_id)}">
                      ${escapeHtml(String(document.document_id).slice(0, 8))}
                    </span>
                  </span>
                </span>
              </td>
              <td class="is-numeric">${escapeHtml(String(document.page_count ?? 0))}</td>
              <td class="is-numeric">${escapeHtml(formatNumber(document.word_count))}</td>
              <td class="is-numeric">${escapeHtml(String(document.chunk_count ?? 0))}</td>
              <td class="is-numeric">${escapeHtml(formatBytes(document.size_bytes))}</td>
              <td>
                <span class="badge badge--${escapeHtml(STATUS_TONES[document.status] || 'neutral')}">
                  ${escapeHtml(String(document.status || 'processed'))}
                </span>
              </td>
              <td title="${escapeHtml(formatDateTime(document.created_at))}">
                ${escapeHtml(formatRelativeTime(document.created_at))}
              </td>
            </tr>`,
            )
            .join('')}
        </tbody>
      </table>
    </div>`;
}

function sum(rows, key) {
  return rows.reduce((total, row) => total + (Number(row[key]) || 0), 0);
}