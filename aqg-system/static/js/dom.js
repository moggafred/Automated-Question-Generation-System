/**
 * DOM and formatting helpers.
 *
 * Everything user-supplied passes through `escapeHtml` before it reaches
 * `innerHTML`. Pages build markup with tagged template literals and rely on
 * `html` here to render it safely.
 */

/** Escapes text for safe interpolation into HTML markup. */
export function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Tagged template that escapes every interpolated value. */
export function html(strings, ...values) {
  return strings.reduce((out, chunk, index) => {
    if (index === 0) return chunk;
    const value = values[index - 1];
    const rendered = Array.isArray(value) ? value.join('') : value;
    return out + (rendered && rendered.__safe ? rendered : escapeHtml(rendered)) + chunk;
  }, '');
}

/** Marks a string as pre-escaped so `html` will not double-escape it. */
export function raw(markup) {
  return { __safe: true, toString: () => String(markup) };
}

/** Marks a list of values as pre-escaped markup. */
export function rawList(items) {
  return raw(items.join(''));
}

/** Queries a single element. */
export function $(selector, scope = document) {
  return scope.querySelector(selector);
}

/** Queries all matching elements as a real array. */
export function $$(selector, scope = document) {
  return Array.from(scope.querySelectorAll(selector));
}

/** Creates an element with attributes and children in one call. */
export function el(tag, attributes = {}, children = []) {
  const node = document.createElement(tag);

  for (const [key, value] of Object.entries(attributes)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, String(value));
  }

  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }

  return node;
}

/** Replaces the children of a container with the given nodes or markup. */
export function replace(container, content) {
  if (!container) return;
  container.innerHTML = '';
  if (typeof content === 'string') container.innerHTML = content;
  else [].concat(content).forEach((child) => container.append(child));
}

// -- Formatting ----------------------------------------------------------

/** Thousands-separated integer, e.g. `1,204`. */
export function formatNumber(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '0';
  return new Intl.NumberFormat().format(numeric);
}

/** Compact number for stat tiles, e.g. `12.4k`. */
export function formatCompact(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '0';
  return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(numeric);
}

/** Fixed-decimal percentage, e.g. `82.5%`. */
export function formatPercent(value, digits = 1) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '0%';
  return `${numeric.toFixed(digits).replace(/\.0$/, '')}%`;
}

/** Human duration from seconds, e.g. `4m 12s`. */
export function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  if (total < 60) return `${total}s`;

  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  if (minutes < 60) return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`;

  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

/** Relative time from an ISO timestamp, e.g. `3h ago`. */
export function formatRelativeTime(value) {
  if (!value) return '—';

  const then = new Date(value);
  if (Number.isNaN(then.getTime())) return '—';

  const deltaSeconds = Math.round((Date.now() - then.getTime()) / 1000);
  const absolute = Math.abs(deltaSeconds);

  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  if (absolute < 60) return formatter.format(-deltaSeconds, 'second');
  if (absolute < 3600) return formatter.format(-Math.round(deltaSeconds / 60), 'minute');
  if (absolute < 86400) return formatter.format(-Math.round(deltaSeconds / 3600), 'hour');
  if (absolute < 2592000) return formatter.format(-Math.round(deltaSeconds / 86400), 'day');
  if (absolute < 31536000) return formatter.format(-Math.round(deltaSeconds / 2592000), 'month');
  return formatter.format(-Math.round(deltaSeconds / 31536000), 'year');
}

/** Absolute date and time from an ISO timestamp. */
export function formatDateTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

/** Short date only, e.g. `4 Mar 2026`. */
export function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(date);
}

/** File size in human units. */
export function formatBytes(bytes) {
  const numeric = Number(bytes);
  if (!Number.isFinite(numeric) || numeric <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const exponent = Math.min(units.length - 1, Math.floor(Math.log(numeric) / Math.log(1024)));
  const scaled = numeric / 1024 ** exponent;
  return `${scaled.toFixed(exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

/** Turns a kebab/snake value into Title Case, e.g. `short-answer` → `Short Answer`. */
export function titleCase(value) {
  if (!value) return '';
  return String(value)
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

/** First non-empty string from the supplied candidates. */
export function firstOf(...values) {
  return values.find((value) => value !== null && value !== undefined && value !== '') ?? '';
}

/** Clamps a number between a minimum and maximum. */
export function clamp(value, min, max) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return min;
  return Math.min(max, Math.max(min, numeric));
}

/** Toggles the reduced-motion flag for one-off animations. */
export function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// -- Loading, empty and error states ------------------------------------

/** Full-page loading state markup. */
export function loadingState(title = 'Loading…', text = 'Fetching the latest data.') {
  return `
    <div class="card"><div class="card__body">
      <div class="loading-panel">
        <span class="spinner spinner--lg" aria-hidden="true"></span>
        <p class="loading-panel__title">${escapeHtml(title)}</p>
        <p class="loading-panel__text">${escapeHtml(text)}</p>
      </div>
    </div></div>`;
}

/** Card-level skeleton placeholders shown while a section loads. */
export function skeletonCards(count = 3, height = '108px') {
  return `
    <div class="stat-grid">
      ${Array.from({ length: count }, () => `<div class="skeleton" style="height:${height}"></div>`).join('')}
    </div>`;
}

/** Empty state with an optional call to action. */
export function emptyState({ icon = 'inbox', title, text, action = '' }) {
  return `
    <div class="state">
      <span class="state__icon" data-icon-slot="${escapeHtml(icon)}" aria-hidden="true"></span>
      <p class="state__title">${escapeHtml(title)}</p>
      ${text ? `<p class="state__text">${escapeHtml(text)}</p>` : ''}
      ${action}
    </div>`;
}

/** Error state that offers a retry affordance. */
export function errorState({ title = 'Something went wrong', text, retryId = 'retry-button' }) {
  return `
    <div class="state">
      <span class="state__icon" data-tone="danger" style="background:var(--danger-50);border-color:var(--danger-200);color:var(--danger-700)" aria-hidden="true">
        <span data-icon-slot="alert" style="display:flex"></span>
      </span>
      <p class="state__title">${escapeHtml(title)}</p>
      ${text ? `<p class="state__text">${escapeHtml(text)}</p>` : ''}
      <button type="button" class="btn btn--secondary" id="${escapeHtml(retryId)}">
        <span data-icon-slot="refresh" style="display:flex"></span> Try again
      </button>
    </div>`;
}

/** Progress bar markup. */
export function progressBar(percentage, tone = null) {
  const width = clamp(percentage, 0, 100);
  const toneAttr = tone ? ` data-tone="${escapeHtml(tone)}"` : '';
  return `
    <div class="progress" role="progressbar" aria-valuenow="${width}" aria-valuemin="0" aria-valuemax="100">
      <div class="progress__bar"${toneAttr} style="width:${width}%"></div>
    </div>`;
}

/** Picks a progress tone from a percentage score. */
export function toneForScore(percentage) {
  const numeric = Number(percentage) || 0;
  if (numeric >= 80) return 'success';
  if (numeric >= 60) return 'warning';
  return 'danger';
}

/** Badge markup for a percentage result. */
export function scoreBadge(percentage) {
  const numeric = Number(percentage) || 0;
  const tone = numeric >= 80 ? 'success' : numeric >= 60 ? 'warning' : 'danger';
  return `<span class="badge badge--${tone}">${escapeHtml(formatPercent(numeric, 0))}</span>`;
}

/** Debounces a function by the given delay in milliseconds. */
export function debounce(fn, delay = 250) {
  let timer = null;
  return (...args) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

/** Injects SVG icons into every `[data-icon-slot]` inside a root element. */
export function hydrateIcons(root, renderIcon) {
  const slots = $$('[data-icon-slot]', root);
  slots.forEach((slot) => {
    const name = slot.dataset.iconSlot || slot.closest('[data-icon]')?.dataset.icon;
    if (!name) return;
    slot.innerHTML = renderIcon(name, { size: Number(slot.dataset.size) || 20 });
  });
}