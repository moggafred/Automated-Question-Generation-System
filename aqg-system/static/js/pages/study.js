/**
 * Study: generate document-grounded revision resources and browse saved ones.
 */

import {
  deleteStudyMaterial,
  generateStudyMaterial,
  getStudyMaterial,
  listStudyMaterials,
} from '../api.js';
import {
  escapeHtml,
  errorState,
  formatRelativeTime,
  hydrateIcons,
  loadingState,
  titleCase,
} from '../dom.js';
import { icon } from '../icons.js';
import { getStudyPrefs, getStudyTypes, saveStudyPrefs } from '../store.js';
import { bindDropzone, renderFileSelection, setStageProgress, stagesMarkup, validateFile } from '../upload.js';
import { confirmDialog, toastError, toastSuccess } from '../toast.js';

const STAGES = [
  { id: 'upload', label: 'Reading your document' },
  { id: 'retrieve', label: 'Selecting the most useful passages' },
  { id: 'generate', label: 'Writing summaries, cards and notes' },
  { id: 'save', label: 'Saving the study pack' },
];

export default async function render({ params, query }) {
  if (params.materialId) return renderSaved(params.materialId);
  return renderStudio(query);
}

// -- Generator + library -------------------------------------------------

async function renderStudio(query) {
  const types = getStudyTypes();
  const prefs = getStudyPrefs();
  const selectedType = query.type || prefs.type || 'summary';

  let library = { materials: [], total: 0 };
  try {
    library = await listStudyMaterials({ limit: 12 });
  } catch {
    library = { materials: [], total: 0 };
  }

  const content = `
    <div class="page__header page__header--row">
      <div>
        <h1 class="page__title">Study materials</h1>
        <p class="page__subtitle">
          Turn the same document into summaries, key concepts, flashcards, definitions and revision
          notes. Everything is grounded in retrieved passages, never invented.
        </p>
      </div>
    </div>

    <form class="split split--sidebar" id="study-form" novalidate>
      <div class="card-stack">
        <section class="card">
          <div class="card__header">
            <div>
              <h2 class="card__title">1. Choose your material</h2>
              <p class="card__subtitle">PDF or TXT learning material</p>
            </div>
          </div>
          <div class="card__body">
            <div class="dropzone" id="dropzone">
              <span class="dropzone__icon" data-icon-slot="upload"></span>
              <p class="dropzone__title">Drop your document here</p>
              <p class="dropzone__text">or click to browse your files</p>
              <p class="dropzone__hint">We index the text and retrieve the most relevant sections.</p>
            </div>
            <div class="file-chip" id="file-chip" hidden></div>
            <p class="field__error" id="file-error" hidden></p>
            <input type="file" id="file-input" accept=".pdf,.txt" class="visually-hidden" />
          </div>
        </section>

        <section class="card">
          <div class="card__header">
            <div>
              <h2 class="card__title">2. Pick a resource</h2>
              <p class="card__subtitle">Full Study Pack generates every resource at once</p>
            </div>
          </div>
          <div class="card__body" style="display:flex;flex-direction:column;gap:var(--space-4)">
            <div class="choice-grid">
              ${types
                .map(
                  (type) => `
                <label class="choice">
                  <input type="radio" name="study-type" value="${escapeHtml(type.value)}"
                    ${type.value === selectedType ? 'checked' : ''} />
                  <span class="choice__indicator" aria-hidden="true"></span>
                  <span class="choice__content">
                    <span class="choice__title">${escapeHtml(type.label)}</span>
                  </span>
                </label>`,
                )
                .join('')}
            </div>

            <div class="field">
              <label class="field__label" for="study-topic">Topic focus <span class="field__hint">(optional)</span></label>
              <input
                class="input"
                id="study-topic"
                type="text"
                maxlength="200"
                placeholder="e.g. Enzyme kinetics"
                value="${escapeHtml(prefs.topic || '')}"
              />
              <p class="field__hint">Leave blank to cover the whole document.</p>
            </div>
          </div>
        </section>
      </div>

      <aside class="card-stack" data-rail>
        <section class="card">
          <div class="card__header"><h2 class="card__title">Generate</h2></div>
          <div class="card__body" style="display:flex;flex-direction:column;gap:var(--space-4)">
            <button type="submit" class="btn btn--primary btn--lg btn--block" id="study-submit">
              <span class="btn__icon" data-icon-slot="sparkle" style="display:flex"></span>
              Create study pack
            </button>
            <p class="field__hint" style="text-align:center">A full pack takes a little longer than a single resource.</p>
          </div>
        </section>

        <section class="card" id="study-progress" hidden>
          <div class="card__header"><h2 class="card__title">Working</h2></div>
          <div class="card__body">${stagesMarkup(STAGES)}</div>
        </section>
      </aside>
    </form>

    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">Saved study materials</h2>
          <p class="card__subtitle">
            ${escapeHtml(String(library.total || 0))} resource(s) stored for you
          </p>
        </div>
      </div>
      <div class="card__body card__body--flush">
        ${
          library.materials?.length
            ? `<div class="record-list">${library.materials.map(materialRow).join('')}</div>`
            : `<div class="state">
                 <span class="state__icon" data-icon-slot="book"></span>
                 <p class="state__title">No study materials yet</p>
                 <p class="state__text">Generate your first pack above and it will be saved here for revision later.</p>
               </div>`
        }
      </div>
    </section>`;

  return {
    title: 'Study Materials',
    breadcrumb: 'Learn from your document',
    content,
    mount(root) {
      hydrateIcons(root, icon);

      let selectedFile = null;
      let inFlight = null;
      const form = root.querySelector('#study-form');
      const fileInput = root.querySelector('#file-input');
      const topicInput = root.querySelector('#study-topic');
      const submitButton = root.querySelector('#study-submit');
      const progressCard = root.querySelector('#study-progress');

      const selectedTypeValue = () =>
        form.querySelector('input[name="study-type"]:checked')?.value || 'summary';

      const unbind = bindDropzone(root, {
        inputId: 'file-input',
        onSelect(file) {
          if (!file) return;
          const problem = validateFile(file, { allowedExtensions: ['.pdf', '.txt'], maxUploadBytes: 10 * 1024 * 1024 });
          if (problem) {
            toastError(problem);
            fileInput.value = '';
            return;
          }
          selectedFile = file;
          renderFileSelection(file, { allowedExtensions: ['.pdf', '.txt'], maxUploadBytes: 10 * 1024 * 1024 });
          hydrateIcons(root, icon);
        },
      });

      root.querySelector('#file-chip').addEventListener('click', (event) => {
        if (!event.target.closest('#clear-file')) return;
        selectedFile = null;
        fileInput.value = '';
        renderFileSelection(null, { allowedExtensions: ['.pdf', '.txt'] });
      });

      root.querySelectorAll('[data-material-id]').forEach((row) => {
        row.addEventListener('click', (event) => {
          if (event.target.closest('[data-role="delete"]')) return;
          window.location.hash = `#/study/${encodeURIComponent(row.dataset.materialId)}`;
        });
      });

      root.querySelectorAll('[data-role="delete"]').forEach((button) => {
        button.addEventListener('click', async (event) => {
          event.stopPropagation();
          const id = button.dataset.id;
          const confirmed = await confirmDialog({
            title: 'Delete this study material?',
            text: 'This removes the saved resource permanently.',
            confirmLabel: 'Delete',
          });
          if (!confirmed) return;

          try {
            await deleteStudyMaterial(id);
            toastSuccess('Study material deleted.');
            button.closest('.activity-item')?.remove();
          } catch (error) {
            toastError(error.message);
          }
        });
      });

      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (inFlight) return;

        if (!selectedFile) {
          toastError('Please choose a document to upload.');
          root.querySelector('#dropzone').focus();
          return;
        }

        const config = { type: selectedTypeValue(), topic: topicInput.value.trim() };
        saveStudyPrefs(config);

        submitButton.disabled = true;
        progressCard.hidden = false;
        setStageProgress(root, 0);

        inFlight = new AbortController();
        const timeout = setTimeout(() => inFlight.abort(), 180000);
        const ticker = setInterval(() => {
          const stages = Array.from(root.querySelectorAll('[data-stage]'));
          const active = stages.findIndex((stage) => stage.dataset.state === 'active');
          if (active >= 0 && active < STAGES.length - 1) setStageProgress(root, active + 1);
        }, 8000);

        try {
          const payload = await generateStudyMaterial(
            selectedFile,
            config,
            { signal: inFlight.signal },
          );
          setStageProgress(root, STAGES.length);
          toastSuccess(`${payload.label || 'Study material'} is ready.`);
          window.location.hash = `#/study/${encodeURIComponent(payload.material.id)}`;
        } catch (error) {
          submitButton.disabled = false;
          progressCard.hidden = true;
          toastError(
            error.name === 'AbortError' ? 'Generation timed out. Please try again.' : error.message,
          );
        } finally {
          clearTimeout(timeout);
          clearInterval(ticker);
          inFlight = null;
        }
      });

      return () => unbind();
    },
  };
}

function materialRow(material) {
  const href = `#/study/${encodeURIComponent(material.material_id)}`;

  return `
    <div class="activity-item" data-material-id="${escapeHtml(material.material_id)}">
      <a class="activity-item__link" href="${href}">
        <span class="activity-item__icon" data-kind="study_material" data-icon-slot="book"></span>
        <span class="activity-item__body">
          <span class="activity-item__title">${escapeHtml(material.title)}</span>
          <span class="activity-item__meta">
            <span class="badge badge--info">${escapeHtml(material.label || titleCase(material.material_type))}</span>
            <span>${escapeHtml(material.topic || 'Full document')}</span>
            <span>&middot;</span>
            <span>${escapeHtml(formatRelativeTime(material.created_at))}</span>
          </span>
        </span>
      </a>
      <button type="button" class="btn btn--ghost btn--icon-only no-print" data-role="delete" data-id="${escapeHtml(material.material_id)}" aria-label="Delete ${escapeHtml(material.title)}">
        <span data-icon-slot="trash" style="display:flex"></span>
      </button>
    </div>`;
}

// -- Saved resource viewer ----------------------------------------------

async function renderSaved(materialId) {
  let payload;
  try {
    payload = await getStudyMaterial(materialId);
  } catch (error) {
    return {
      title: 'Study material unavailable',
      content: `<div class="card"><div class="card__body">${errorState({
        title: error.isNotFound ? 'Study material not found' : 'Could not load this resource',
        text: error.message,
        retryId: 'study-retry',
      })}</div></div>`,
      mount(root) {
        hydrateIcons(root, icon);
        root.querySelector('#study-retry')?.addEventListener('click', () => {
          window.location.hash = '#/study';
        });
      },
    };
  }

  const record = payload.material || {};
  // Stored records nest the generated blocks under `content`, while a freshly
  // generated payload carries them at the top level.
  const material = record.content || record;
  const sections = [
    summarySection(material.summary),
    conceptsSection(material.key_concepts),
    flashcardsSection(material.flashcards),
    definitionsSection(material.definitions),
    notesSection(material.revision_notes),
  ].filter(Boolean);

  const content = `
    <div class="page__header page__header--row">
      <div>
        <p class="badge badge--brand">${escapeHtml(payload.label || titleCase(record.material_type))}</p>
        <h1 class="page__title">${escapeHtml(record.title || 'Study material')}</h1>
        <p class="page__subtitle">
          ${escapeHtml(record.topic || 'Full document')} &middot;
          from ${escapeHtml(record.source_filename || 'your document')} &middot;
          ${escapeHtml(formatRelativeTime(record.created_at))}
        </p>
      </div>
      <div class="page__actions no-print">
        <a class="btn btn--secondary" href="#/study">
          <span class="btn__icon" data-icon-slot="chevronLeft" style="display:flex"></span> All materials
        </a>
        <a class="btn btn--primary" href="#/generate">
          <span class="btn__icon" data-icon-slot="quiz" style="display:flex"></span> Test yourself
        </a>
      </div>
    </div>

    ${
      sections.length
        ? `<div class="card-stack">${sections.join('')}</div>`
        : `${loadingState('Nothing stored', 'This resource has no content.')}`
    }`;

  return {
    title: record.title || 'Study Material',
    breadcrumb: payload.label || 'Saved resource',
    content,
    mount(root) {
      hydrateIcons(root, icon);
      root.querySelectorAll('.flashcard').forEach((card) => {
        card.addEventListener('click', () => {
          card.dataset.flipped = card.dataset.flipped === 'true' ? 'false' : 'true';
        });
        card.addEventListener('keydown', (event) => {
          if (event.key !== 'Enter' && event.key !== ' ') return;
          event.preventDefault();
          card.dataset.flipped = card.dataset.flipped === 'true' ? 'false' : 'true';
        });
        card.tabIndex = 0;
        card.setAttribute('role', 'button');
        card.setAttribute('aria-label', 'Flashcard: activate to flip');
      });
    },
  };
}

function summarySection(summary) {
  if (!summary) return '';
  return `
    <section class="card">
      <div class="card__header">
        <h2 class="card__title">${escapeHtml(summary.title || 'Summary')}</h2>
      </div>
      <div class="card__body prose-block">
        ${summary.overview ? `<p class="prose-block__text">${escapeHtml(summary.overview)}</p>` : ''}
        ${
          summary.points?.length
            ? `<ul class="bullet-list">
                 ${summary.points
                   .map(
                     (point) => `
                   <li class="bullet-list__item">
                     <span class="bullet-list__marker">${icon('check', { size: 12 })}</span>
                     ${escapeHtml(point)}
                   </li>`,
                   )
                   .join('')}
                 </ul>`
            : ''
        }
        ${
          summary.learning_outcomes?.length
            ? `<div class="prose-block">
                 <p class="prose-block__title">
                   <span data-icon-slot="target" style="display:flex"></span> Learning outcomes
                 </p>
                 <ul class="bullet-list">
                   ${summary.learning_outcomes
                     .map(
                       (outcome) => `
                     <li class="bullet-list__item">
                       <span class="bullet-list__marker">${icon('check', { size: 12 })}</span>
                       ${escapeHtml(outcome)}
                     </li>`,
                     )
                     .join('')}
                 </ul>
               </div>`
            : ''
        }
      </div>
    </section>`;
}

function conceptsSection(concepts) {
  if (!concepts?.length) return '';
  return `
    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">Key concepts</h2>
          <p class="card__subtitle">${escapeHtml(String(concepts.length))} idea(s) worth remembering</p>
        </div>
      </div>
      <div class="card__body">
        <div class="concept-grid">
          ${concepts
            .map(
              (concept) => `
            <div class="concept-card">
              <p class="concept-card__title">${escapeHtml(concept.title)}</p>
              <p class="concept-card__body">${escapeHtml(concept.description)}</p>
              ${
                concept.why_it_matters
                  ? `<p class="concept-card__why"><strong>Why it matters:</strong> ${escapeHtml(concept.why_it_matters)}</p>`
                  : ''
              }
            </div>`,
            )
            .join('')}
        </div>
      </div>
    </section>`;
}

function flashcardsSection(flashcards) {
  if (!flashcards?.length) return '';
  return `
    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">Flashcards</h2>
          <p class="card__subtitle">Tap a card to flip it &mdash; ${escapeHtml(String(flashcards.length))} card(s)</p>
        </div>
      </div>
      <div class="card__body">
        <div class="flashcard-grid">
          ${flashcards
            .map(
              (card) => `
            <div class="flashcard" data-flipped="false">
              <div class="flashcard__inner">
                <div class="flashcard__face flashcard__face--front">
                  <span class="flashcard__label">Question</span>
                  <p class="flashcard__text">${escapeHtml(card.front)}</p>
                  ${card.hint ? `<p class="flashcard__hint">Hint: ${escapeHtml(card.hint)}</p>` : ''}
                </div>
                <div class="flashcard__face flashcard__face--back">
                  <span class="flashcard__label">Answer</span>
                  <p class="flashcard__text">${escapeHtml(card.back)}</p>
                  ${card.topic ? `<p class="flashcard__hint">${escapeHtml(card.topic)}</p>` : ''}
                </div>
              </div>
            </div>`,
            )
            .join('')}
        </div>
      </div>
    </section>`;
}

function definitionsSection(definitions) {
  if (!definitions?.length) return '';
  return `
    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">Important definitions</h2>
          <p class="card__subtitle">Terminology you should be able to recall</p>
        </div>
      </div>
      <div class="card__body">
        <div class="definition-list">
          ${definitions
            .map(
              (definition) => `
            <div class="definition-item">
              <p class="definition-item__term">${escapeHtml(definition.term)}</p>
              <p class="definition-item__body">${escapeHtml(definition.definition)}</p>
              ${definition.example ? `<p class="definition-item__example">e.g. ${escapeHtml(definition.example)}</p>` : ''}
            </div>`,
            )
            .join('')}
        </div>
      </div>
    </section>`;
}

function notesSection(notes) {
  if (!notes?.length) return '';
  return `
    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">Revision notes</h2>
          <p class="card__subtitle">Structured notes for a final pass</p>
        </div>
      </div>
      <div class="card__body card__body--flush">
        <div class="record-list">
          ${notes
            .map(
              (note) => `
            <div class="review-item">
              <p class="prose-block__title">${escapeHtml(note.heading)}</p>
              <p class="prose-block__text">${escapeHtml(note.body)}</p>
              ${
                note.key_takeaway
                  ? `<div class="explanation"><strong>Key takeaway:</strong> ${escapeHtml(note.key_takeaway)}</div>`
                  : ''
              }
            </div>`,
            )
            .join('')}
        </div>
      </div>
    </section>`;
}