/**
 * Toast notifications.
 *
 * Toasts are announced politely, are keyboard dismissible, and auto-expire so
 * they never block the interface.
 */

import { $, escapeHtml } from './dom.js';
import { icon } from './icons.js';

const TONE_ICONS = {
  success: 'checkCircle',
  error: 'alert',
  warning: 'alert',
  info: 'info',
};

const DEFAULT_DURATION = 5000;

function region() {
  let node = $('#toast-region');
  if (!node) {
    node = document.createElement('div');
    node.id = 'toast-region';
    node.className = 'toast-region';
    node.setAttribute('role', 'status');
    node.setAttribute('aria-live', 'polite');
    document.body.append(node);
  }
  return node;
}

function dismiss(toast) {
  if (!toast.isConnected) return;
  toast.style.opacity = '0';
  toast.style.transform = 'translateX(16px)';
  setTimeout(() => toast.remove(), 180);
}

/**
 * Shows a transient notification.
 *
 * @param {string} message End-user-facing text.
 * @param {{tone?: 'success'|'error'|'warning'|'info', duration?: number, title?: string}} [options]
 */
export function toast(message, options = {}) {
  if (!message) return null;

  const tone = options.tone || 'info';
  const duration = options.duration ?? (tone === 'error' ? 8000 : DEFAULT_DURATION);

  const node = document.createElement('div');
  node.className = 'toast';
  node.dataset.tone = tone;
  node.innerHTML = `
    <span class="toast__icon">${icon(TONE_ICONS[tone] || 'info', { size: 20 })}</span>
    <div class="toast__message">
      ${options.title ? `<strong>${escapeHtml(options.title)}</strong><br />` : ''}
      ${escapeHtml(message)}
    </div>
    <button type="button" class="toast__close" aria-label="Dismiss notification">
      ${icon('close', { size: 16 })}
    </button>`;

  node.querySelector('.toast__close').addEventListener('click', () => dismiss(node));
  region().append(node);

  if (duration > 0) {
    const timer = setTimeout(() => dismiss(node), duration);
    node.addEventListener('mouseenter', () => clearTimeout(timer), { once: true });
  }

  return node;
}

export const toastSuccess = (message, options) => toast(message, { ...options, tone: 'success' });
export const toastError = (message, options) => toast(message, { ...options, tone: 'error' });
export const toastInfo = (message, options) => toast(message, { ...options, tone: 'info' });
export const toastWarning = (message, options) => toast(message, { ...options, tone: 'warning' });

/** Confirmation dialog; resolves true when the learner confirms. */
export function confirmDialog({ title, text, confirmLabel = 'Confirm', tone = 'danger' }) {
  return new Promise((resolve) => {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <div class="modal__body">
          <p class="modal__title" id="confirm-title">${escapeHtml(title)}</p>
          ${text ? `<p class="modal__text">${escapeHtml(text)}</p>` : ''}
        </div>
        <div class="modal__actions">
          <button type="button" class="btn btn--ghost" data-role="cancel">Cancel</button>
          <button type="button" class="btn btn--${escapeHtml(tone)}" data-role="confirm">${escapeHtml(confirmLabel)}</button>
        </div>
      </div>`;

    const finish = (value) => {
      document.removeEventListener('keydown', onKeydown);
      backdrop.remove();
      resolve(value);
    };

    const onKeydown = (event) => {
      if (event.key === 'Escape') finish(false);
    };

    backdrop.addEventListener('click', (event) => {
      if (event.target === backdrop) finish(false);
    });
    backdrop.querySelector('[data-role="cancel"]').addEventListener('click', () => finish(false));
    backdrop.querySelector('[data-role="confirm"]').addEventListener('click', () => finish(true));
    document.addEventListener('keydown', onKeydown);

    document.body.append(backdrop);
    backdrop.querySelector('[data-role="confirm"]').focus();
  });
}