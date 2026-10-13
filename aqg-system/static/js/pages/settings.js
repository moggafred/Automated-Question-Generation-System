/**
 * Settings: appearance preferences plus a read-only view of platform status.
 *
 * Generation limits and provider credentials are server-side configuration, so
 * this page reports them rather than pretending to change them.
 */

import { getStatus } from '../api.js';
import { escapeHtml, formatDateTime, hydrateIcons, titleCase } from '../dom.js';
import { icon } from '../icons.js';
import {
  getDifficultyLevels,
  getQuestionTypes,
  getStudyTypes,
  getTheme,
  setSidebarCollapsed,
  setTheme,
} from '../store.js';
import { toastSuccess } from '../toast.js';

export default async function render() {
  let status = null;
  try {
    status = await getStatus();
  } catch {
    status = null;
  }

  const services = status?.services || {};
  const limits = status?.limits || {};
  const statistics = status?.statistics || {};

  const content = `
    <div class="page__header">
      <h1 class="page__title">Settings</h1>
      <p class="page__subtitle">
        Appearance preferences are stored in this browser. Server configuration is reported so you
        can see exactly what the platform is running with.
      </p>
    </div>

    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">Appearance</h2>
          <p class="card__subtitle">Applied instantly and remembered on this device</p>
        </div>
      </div>
      <div class="card__body card__body--flush">
        <div class="settings-group">
          <div class="settings-row">
            <div>
              <p class="settings-row__label">Colour theme</p>
              <p class="settings-row__hint">
                Light and dark both meet contrast requirements. Your choice is stored locally.
              </p>
            </div>
            <label class="switch">
              <input type="checkbox" id="theme-switch" ${getTheme() === 'dark' ? 'checked' : ''}
                aria-label="Use the dark theme" />
              <span class="switch__track" aria-hidden="true"></span>
              <span class="switch__thumb" aria-hidden="true"></span>
            </label>
          </div>
          <div class="settings-row">
            <div>
              <p class="settings-row__label">Compact sidebar</p>
              <p class="settings-row__hint">Collapse navigation to icons only on desktop screens.</p>
            </div>
            <button type="button" class="btn btn--secondary btn--sm" id="toggle-sidebar">
              <span data-icon-slot="chevronLeft" style="display:flex"></span> Toggle
            </button>
          </div>
        </div>
      </div>
    </section>

    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">Platform status</h2>
          <p class="card__subtitle">
            ${status
              ? `${escapeHtml(status.app_name)} v${escapeHtml(status.version)} &middot; ${escapeHtml(titleCase(status.environment))} mode`
              : 'Status could not be read from the server'}
          </p>
        </div>
      </div>
      <div class="card__body card__body--flush">
        <div class="settings-group">
          ${serviceRow('database', 'Database', services.database?.status, services.database?.path)}
          ${serviceRow('cpu', 'AI provider', services.llm?.status, `${services.llm?.provider || 'unknown'} · ${services.llm?.model || ''}`)}
          ${serviceRow('layers', 'Retrieval', services.retrieval?.status, `top ${services.retrieval?.top_k ?? '—'} · ${services.retrieval?.embedding_dim ?? '—'} dims`)}
        </div>
      </div>
    </section>

    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">Server configuration</h2>
          <p class="card__subtitle">Read-only. Change these through environment variables.</p>
        </div>
      </div>
      <div class="card__body card__body--flush">
        <div class="settings-group">
          ${row('Maximum upload', `${limits.max_upload_mb ?? '—'}MB`)}
          ${row('Accepted formats', (limits.allowed_extensions || []).map((item) => item.toUpperCase()).join(', ') || '—')}
          ${row('Questions per assessment', `${limits.min_questions ?? '—'} to ${limits.max_questions ?? '—'}`)}
          ${row('Server time', formatDateTime(status?.server_time))}
        </div>
      </div>
    </section>

    <div class="split split--aside">
      <section class="card">
        <div class="card__header"><h2 class="card__title">Question formats</h2></div>
        <div class="card__body">
          <div class="tag-row">
            ${getQuestionTypes()
              .map(
                (type) => `<span class="badge badge--brand">${escapeHtml(type.label)}</span>`,
              )
              .join('')}
          </div>
        </div>
      </section>

      <section class="card">
        <div class="card__header"><h2 class="card__title">Study resources</h2></div>
        <div class="card__body">
          <div class="tag-row">
            ${getStudyTypes()
              .map((type) => `<span class="badge badge--info">${escapeHtml(type.label)}</span>`).join('')}
          </div>
          <div class="tag-row" style="margin-top:var(--space-3)">
            ${getDifficultyLevels()
              .map(
                (level) => `<span class="badge badge--neutral">${escapeHtml(level.label)}</span>`,
              )
              .join('')}
          </div>
        </div>
      </section>
    </div>

    <section class="card">
      <div class="card__header"><h2 class="card__title">Your data</h2></div>
      <div class="card__body card__body--flush">
        <div class="settings-group">
          ${row('Documents processed', statistics.documents_processed ?? 0)}
          ${row('Assessments generated', statistics.quizzes_generated ?? 0)}
          ${row('Study resources created', statistics.study_materials_generated ?? 0)}
          ${row('Assessments completed', statistics.assessments_completed ?? 0)}
        </div>
      </div>
      <div class="card__footer">
        <p class="field__hint">
          Everything you generate is stored in a local SQLite database on the server. Nothing is
          shared with third parties and no personal data is collected.
        </p>
        <div class="page__actions" style="margin-top:var(--space-3)">
          <a class="btn btn--secondary" href="#/documents">Browse documents</a>
          <a class="btn btn--secondary" href="#/history">Browse history</a>
        </div>
      </div>
    </section>`;

  let detachThemeListener = null;

  return {
    title: 'Settings',
    breadcrumb: 'Preferences and platform status',
    content,
    mount(root) {
      hydrateIcons(root, icon);

      const themeSwitch = root.querySelector('#theme-switch');
      const syncThemeSwitch = () => {
        if (themeSwitch) themeSwitch.checked = getTheme() === 'dark';
      };
      document.addEventListener('aqg:themechange', syncThemeSwitch);
      detachThemeListener = () => document.removeEventListener('aqg:themechange', syncThemeSwitch);

      themeSwitch.addEventListener('change', (event) => {
        setTheme(event.target.checked ? 'dark' : 'light');
        toastSuccess(`Switched to the ${event.target.checked ? 'dark' : 'light'} theme.`);
      });

      root.querySelector('#toggle-sidebar').addEventListener('click', () => {
        const shell = document.getElementById('app-shell');
        const collapsed = shell?.dataset.sidebar !== 'collapsed';
        if (shell) shell.dataset.sidebar = collapsed ? 'collapsed' : 'expanded';
        setSidebarCollapsed(collapsed);
        toastSuccess(collapsed ? 'Sidebar collapsed.' : 'Sidebar expanded.');
      });
    },
    cleanup() {
      detachThemeListener?.();
    },
  };
}

function row(label, value) {
  return `
    <div class="settings-row">
      <span class="settings-row__label">${escapeHtml(label)}</span>
      <span class="settings-row__value">${escapeHtml(String(value))}</span>
    </div>`;
}

function serviceRow(iconName, label, status, detail) {
  const normalized = String(status || 'unknown').toLowerCase();
  const state = /online|configured|ready|ok|success/.test(normalized)
    ? 'online'
    : /degraded|error|failed/.test(normalized)
      ? 'degraded'
      : 'pending';

  return `
    <div class="settings-row">
      <div style="display:flex;align-items:center;gap:var(--space-3);min-width:0">
        <span class="nav-link__icon" data-icon-slot="${escapeHtml(iconName)}"></span>
        <div style="min-width:0">
          <p class="settings-row__label">${escapeHtml(label)}</p>
          ${detail ? `<p class="settings-row__hint">${escapeHtml(detail)}</p>` : ''}
        </div>
      </div>
      <span class="badge badge--${state === 'online' ? 'success' : state === 'degraded' ? 'danger' : 'warning'}">
        <span class="status-dot" data-state="${escapeHtml(state)}" aria-hidden="true"></span>
        ${escapeHtml(String(status || 'unknown'))}
      </span>
    </div>`;
}