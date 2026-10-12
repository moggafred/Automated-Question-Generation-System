/**
 * File upload helpers shared by the Generate and Study pages.
 *
 * Validation happens client-side for fast feedback, using the limits the server
 * reports via `/api/limits`; the server re-validates regardless.
 */

import { escapeHtml, formatBytes } from './dom.js';

/** Extracts a file extension in lower case, including the dot. */
export function extensionOf(file) {
  const name = String(file?.name || '');
  const dot = name.lastIndexOf('.');
  return dot === -1 ? '' : name.slice(dot).toLowerCase();
}

/**
 * Validates a file against the server-provided limits.
 *
 * @param {File} file
 * @param {{allowedExtensions: string[], maxUploadBytes: number}} limits
 * @returns {string|null} An end-user-facing error message, or null when valid.
 */
export function validateFile(file, limits) {
  if (!file) return 'Please choose a document to upload.';

  const extension = extensionOf(file);
  if (!extension) return 'That file has no extension. Please upload a PDF or TXT document.';

  const allowed = (limits.allowedExtensions || []).map((item) => item.toLowerCase());
  if (allowed.length && !allowed.includes(extension)) {
    return `We cannot read ${escapeHtml(extension)} files. Please upload ${allowed
      .map((item) => item.toUpperCase())
      .join(' or ')}.`;
  }

  if (file.size === 0) return 'That file is empty. Please upload a document with readable text.';

  if (limits.maxUploadBytes && file.size > limits.maxUploadBytes) {
    return `That file is ${escapeHtml(formatBytes(file.size))}. The limit is ${escapeHtml(
      formatBytes(limits.maxUploadBytes),
    )}.`;
  }

  return null;
}

/**
 * Wires a dropzone to a hidden file input.
 *
 * @param {HTMLElement} root Page root.
 * @param {{inputId: string, onSelect: (file: File|null) => void}} options
 * @returns {() => void} Cleanup that removes the added listeners.
 */
export function bindDropzone(root, { inputId, onSelect }) {
  const zone = root.querySelector('#dropzone');
  const input = root.querySelector(`#${inputId}`);
  if (!zone || !input) return () => {};

  const openPicker = () => input.click();

  const onZoneClick = (event) => {
    // Let clicks on interactive children bubble without double-opening.
    if (event.target.closest('button, a, label')) return;
    openPicker();
  };

  const onKeydown = (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openPicker();
    }
  };

  const onInputChange = () => {
    const [file] = input.files || [];
    onSelect(file || null);
  };

  const onDragOver = (event) => {
    event.preventDefault();
    zone.dataset.dragging = 'true';
  };

  const onDragLeave = (event) => {
    if (zone.contains(event.relatedTarget)) return;
    zone.dataset.dragging = 'false';
  };

  const onDrop = (event) => {
    event.preventDefault();
    zone.dataset.dragging = 'false';
    const [file] = event.dataTransfer?.files || [];
    onSelect(file || null);
    if (file) input.value = '';
  };

  const onPaste = (event) => {
    const [file] = event.clipboardData?.files || [];
    if (file) onSelect(file);
  };

  zone.addEventListener('click', onZoneClick);
  zone.addEventListener('keydown', onKeydown);
  zone.tabIndex = 0;
  zone.setAttribute('role', 'button');
  input.addEventListener('change', onInputChange);
  zone.addEventListener('dragover', onDragOver);
  zone.addEventListener('dragleave', onDragLeave);
  zone.addEventListener('drop', onDrop);
  zone.addEventListener('paste', onPaste);

  return () => {
    zone.removeEventListener('click', onZoneClick);
    zone.removeEventListener('keydown', onKeydown);
    input.removeEventListener('change', onInputChange);
    zone.removeEventListener('dragover', onDragOver);
    zone.removeEventListener('dragleave', onDragLeave);
    zone.removeEventListener('drop', onDrop);
    zone.removeEventListener('paste', onPaste);
  };
}

/** Renders the selected-file chip and the empty dropzone state. */
export function renderFileSelection(file, limits) {
  const chip = document.getElementById('file-chip');
  const zone = document.getElementById('dropzone');
  const error = document.getElementById('file-error');
  if (!chip || !zone) return;

  if (!file) {
    chip.innerHTML = '';
    chip.hidden = true;
    zone.hidden = false;
    if (error) {
      error.textContent = '';
      error.hidden = true;
    }
    return;
  }

  const problem = validateFile(file, limits);
  if (problem) {
    chip.innerHTML = '';
    chip.hidden = true;
    zone.hidden = false;
    if (error) {
      error.innerHTML = `${iconShield()} ${escapeHtml(problem)}`;
      error.hidden = false;
    }
    return;
  }

  if (error) {
    error.textContent = '';
    error.hidden = true;
  }
  zone.hidden = true;
  chip.hidden = false;
  chip.innerHTML = `
    <span class="file-chip__icon" data-icon-slot="${extensionOf(file) === '.pdf' ? 'fileText' : 'file'}"></span>
    <span class="file-chip__body">
      <span class="file-chip__name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>
      <span class="file-chip__meta">${escapeHtml(formatBytes(file.size))} &middot; ready to process</span>
    </span>
    <button type="button" class="btn btn--ghost btn--sm" id="clear-file" aria-label="Remove selected file">
      <span data-icon-slot="close" style="display:flex"></span> Remove
    </button>`;
}

function iconShield() {
  return `<span style="display:inline-flex;vertical-align:-3px"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg></span>`;
}

/** Progress stage list used while a long generation runs. */
export function stagesMarkup(stages) {
  return `
    <div class="stages">
      ${stages
        .map(
          (stage) => `
        <div class="stage" data-stage="${escapeHtml(stage.id)}" data-state="pending">
          <span class="stage__marker">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7"/></svg>
          </span>
          <span>${escapeHtml(stage.label)}</span>
        </div>`,
        )
        .join('')}
    </div>`;
}

/** Advances the stage list by index; pass -1 to mark everything done. */
export function setStageProgress(container, index) {
  const stages = container?.querySelectorAll('[data-stage]');
  if (!stages) return;

  stages.forEach((stage, position) => {
    if (position < index) stage.dataset.state = 'done';
    else if (position === index) stage.dataset.state = 'active';
    else stage.dataset.state = 'pending';
  });
}