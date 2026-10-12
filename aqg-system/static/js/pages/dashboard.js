/**
 * Dashboard: platform statistics, recent activity and quick actions.
 */

import { getDashboard } from '../api.js';
import {
  escapeHtml,
  errorState,
  formatNumber,
  formatPercent,
  formatRelativeTime,
  scoreBadge,
  toneForScore,
  hydrateIcons,
} from '../dom.js';
import { icon } from '../icons.js';

const ACTIVITY_ICONS = {
  quiz: 'quiz',
  study_material: 'book',
  assessment: 'award',
  document: 'fileText',
};

export default async function render() {
  let data;
  try {
    data = await getDashboard();
  } catch (error) {
    return {
      title: 'Dashboard',
      content: `<div class="card"><div class="card__body">${errorState({
        title: 'The dashboard could not be loaded',
        text: error.message,
      })}</div></div>`,
      mount(root) {
        root.querySelector('#retry-button')?.addEventListener('click', () => {
          window.location.reload();
        });
      },
    };
  }

  const stats = data.statistics || {};
  const activity = data.recent_activity || [];
  const attempts = data.recent_attempts || [];
  const actions = data.quick_actions || [];
  const hasAttempts = (stats.assessments_completed || 0) > 0;

  const content = `
    <section class="hero">
      <div>
        <span class="hero__eyebrow"><span data-icon-slot="sparkle" style="display:flex"></span> Grounded AI assessment</span>
        <h1 class="hero__title">Turn any document into a graded assessment</h1>
        <p class="hero__text">
          Upload PDF or TXT learning material. AQG retrieves the relevant passages, generates
          questions in the format you choose, grades your submission automatically, and tracks
          your progress with real analytics.
        </p>
        <div class="hero__actions">
          <a class="btn btn--primary btn--lg" href="#/generate">
            <span class="btn__icon" data-icon-slot="sparkle" style="display:flex"></span> Generate assessment
          </a>
          <a class="btn btn--secondary btn--lg" href="#/study">
            <span class="btn__icon" data-icon-slot="book" style="display:flex"></span> Create study pack
          </a>
        </div>
      </div>

      <aside class="hero__aside">
        <p class="hero__aside-title">Quick actions</p>
        <div class="hero__list">
          ${actions
            .map(
              (action) => `
            <a class="hero__list-item" href="${escapeHtml(action.href || '#/generate')}">
              <span class="hero__list-icon" data-icon-slot="${escapeHtml(action.icon || 'sparkle')}"></span>
              <span>
                <strong>${escapeHtml(action.label)}</strong><br />
                <span style="color:var(--text-tertiary)">${escapeHtml(action.description)}</span>
              </span>
            </a>`,
            )
            .join('')}
        </div>
      </aside>
    </section>

    <div class="stat-grid">
      ${statTile('quiz', formatNumber(stats.quizzes_generated), 'Assessments generated', 'brand')}
      ${statTile('layers', formatNumber(stats.questions_generated), 'Questions generated', 'info')}
      ${statTile('award', formatNumber(stats.assessments_completed), 'Assessments completed', 'success')}
      ${statTile(
        'trending',
        hasAttempts ? formatPercent(stats.average_score, 0) : '—',
        hasAttempts ? 'Average score' : 'No attempts yet',
        hasAttempts ? toneForScore(stats.average_score) : 'default',
        hasAttempts ? `Best ${formatPercent(stats.highest_score, 0)}` : 'Submit an assessment to start tracking',
      )}
      ${statTile('fileText', formatNumber(stats.documents_processed), 'Documents processed', 'default')}
      ${statTile('book', formatNumber(stats.study_materials_generated), 'Study packs created', 'default')}
    </div>

    <div class="split split--sidebar">
      <section class="card">
        <div class="card__header">
          <div>
            <h2 class="card__title">Recent activity</h2>
            <p class="card__subtitle">Everything you have generated or completed</p>
          </div>
          <a class="btn btn--ghost btn--sm" href="#/history">View history</a>
        </div>
        <div class="card__body card__body--flush">
          ${
            activity.length
              ? `<div class="activity-list">${activity.map(activityItem).join('')}</div>`
              : `<div class="state">
                   <span class="state__icon" data-icon-slot="inbox"></span>
                   <p class="state__title">Nothing here yet</p>
                   <p class="state__text">Generate your first assessment from a document to see activity here.</p>
                   <a class="btn btn--primary" href="#/generate">Get started</a>
                 </div>`
          }
        </div>
      </section>

      <section class="card">
        <div class="card__header">
          <div>
            <h2 class="card__title">Latest attempts</h2>
            <p class="card__subtitle">Most recent graded submissions</p>
          </div>
        </div>
        <div class="card__body card__body--flush">
          ${
            attempts.length
              ? `<div class="record-list">${attempts.map(attemptRow).join('')}</div>`
              : `<div class="state">
                   <span class="state__icon" data-icon-slot="target"></span>
                   <p class="state__title">No attempts yet</p>
                   <p class="state__text">Once you submit an assessment you will see your score and detailed feedback here.</p>
                 </div>`
          }
        </div>
        ${
          attempts.length
            ? `<div class="card__footer"><a class="btn btn--soft btn--block btn--sm" href="#/performance">Open performance analytics</a></div>`
            : ''
        }
      </section>
    </div>

    ${
      hasAttempts
        ? `<section class="card">
             <div class="card__body">
               <div class="alert alert--info">
                 <span class="alert__icon" data-icon-slot="bulb"></span>
                 <div class="alert__body">
                   <p class="alert__title">Keep the streak going</p>
                   You have answered ${escapeHtml(formatNumber(stats.questions_answered || 0))} questions across
                   ${escapeHtml(formatNumber(stats.assessments_completed))} attempts
                   ${stats.topics_covered ? `covering ${escapeHtml(String(stats.topics_covered))} topic(s)` : ''}.
                 </div>
               </div>
             </div>
           </section>`
        : ''
    }`;

  return {
    title: 'Dashboard',
    breadcrumb: 'Overview',
    content,
    mount(root) {
      hydrateIcons(root, icon);
    },
  };
}

function statTile(iconName, value, label, tone = 'default', trend = '') {
  const toneAttr = tone && tone !== 'default' ? ` data-tone="${escapeHtml(tone)}"` : '';
  return `
    <div class="stat">
      <span class="stat__icon"${toneAttr} data-icon-slot="${escapeHtml(iconName)}"></span>
      <div class="stat__body">
        <p class="stat__value">${escapeHtml(value)}</p>
        <p class="stat__label">${escapeHtml(label)}</p>
        ${trend ? `<p class="stat__trend">${escapeHtml(trend)}</p>` : ''}
      </div>
    </div>`;
}

function activityItem(item) {
  const kind = item.kind || 'quiz';
  return `
    <a class="activity-item" href="${escapeHtml(item.href || '#/history')}">
      <span class="activity-item__icon" data-kind="${escapeHtml(kind)}" data-icon-slot="${escapeHtml(ACTIVITY_ICONS[kind] || 'inbox')}"></span>
      <span class="activity-item__body">
        <span class="activity-item__title">${escapeHtml(item.title)}</span>
        <span class="activity-item__meta">
          <span>${escapeHtml(item.subtitle || '')}</span>
          <span>&middot;</span>
          <span>${escapeHtml(formatRelativeTime(item.created_at))}</span>
        </span>
      </span>
    </a>`;
}

function attemptRow(attempt) {
  return `
    <a class="activity-item" href="#/result/${encodeURIComponent(attempt.attempt_id)}">
      <span class="activity-item__icon" data-kind="assessment" data-icon-slot="award"></span>
      <span class="activity-item__body">
        <span class="activity-item__title">${escapeHtml(attempt.quiz_title || 'Assessment')}</span>
        <span class="activity-item__meta">
          <span>${escapeHtml(attempt.topic || 'Full document')}</span>
          <span>&middot;</span>
          <span>${escapeHtml(String(attempt.correct_answers))}/${escapeHtml(String(attempt.total_questions))} correct</span>
          <span>&middot;</span>
          <span>${escapeHtml(formatRelativeTime(attempt.created_at))}</span>
        </span>
      </span>
      ${scoreBadge(attempt.percentage)}
    </a>`;
}