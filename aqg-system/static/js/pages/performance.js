/**
 * Performance: real aggregates derived from stored attempts.
 *
 * Every number comes from `/api/performance`. With no attempt history the page
 * renders an honest empty state instead of placeholder charts.
 */

import { getPerformance } from '../api.js';
import { CHART_COLORS, barList, donutChart, sparkChart } from '../charts.js';
import {
  escapeHtml,
  errorState,
  formatNumber,
  formatPercent,
  formatRelativeTime,
  hydrateIcons,
  toneForScore,
} from '../dom.js';
import { icon } from '../icons.js';

export default async function render() {
  let data;
  try {
    data = await getPerformance();
  } catch (error) {
    return {
      title: 'Performance',
      content: `<div class="card"><div class="card__body">${errorState({
        title: 'Analytics could not be loaded',
        text: error.message,
        retryId: 'performance-retry',
      })}</div></div>`,
      mount(root) {
        hydrateIcons(root, icon);
        root.querySelector('#performance-retry')?.addEventListener('click', () => {
          window.location.reload();
        });
      },
    };
  }

  if (!data.has_data) {
    return {
      title: 'Performance',
      breadcrumb: 'Real analytics from your attempts',
      content: `
        <div class="page__header">
          <h1 class="page__title">Performance</h1>
          <p class="page__subtitle">
            Analytics are computed from your real attempt history. Nothing is estimated or
            pre-filled, so an empty page means nothing has been submitted yet.
          </p>
        </div>
        <section class="card">
          <div class="card__body">
            <div class="state">
              <span class="state__icon" data-icon-slot="trending"></span>
              <p class="state__title">No attempt data yet</p>
              <p class="state__text">
                Generate an assessment, submit it, and this page will show your average score,
                strongest and weakest topics, and score trends.
              </p>
              <a class="btn btn--primary btn--lg" href="#/generate">
                <span class="btn__icon" data-icon-slot="sparkle" style="display:flex"></span> Generate an assessment
              </a>
            </div>
          </div>
        </section>`,
      mount(root) {
        hydrateIcons(root, icon);
      },
    };
  }

  const topics = data.topic_performance || [];
  const recent = data.recent_attempts || [];
  const distribution = data.score_distribution || [];

  // Oldest-first so the spark chart reads left to right.
  const trend = [...recent].reverse();

  const content = `
    <div class="page__header page__header--row">
      <div>
        <h1 class="page__title">Performance</h1>
        <p class="page__subtitle">
          Computed from ${escapeHtml(formatNumber(data.total_assessments))} graded attempt(s) across
          ${escapeHtml(formatNumber(data.questions_answered))} answered question(s).
        </p>
      </div>
      <div class="page__actions">
        <a class="btn btn--secondary" href="#/assessments">
          <span class="btn__icon" data-icon-slot="assessment" style="display:flex"></span> All attempts
        </a>
      </div>
    </div>

    <div class="stat-grid">
      ${tile('trending', formatPercent(data.average_score, 0), 'Average score', toneForScore(data.average_score), `Across ${data.total_assessments} attempt(s)`)}
      ${tile('award', formatPercent(data.highest_score, 0), 'Best score', 'success')}
      ${tile('alert', formatPercent(data.lowest_score, 0), 'Lowest score', 'danger')}
      ${tile('layers', formatNumber(data.questions_answered), 'Questions answered', 'info', `${data.questions_generated} generated`)}
    </div>

    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">Recent score trend</h2>
          <p class="card__subtitle">Your last ${escapeHtml(String(recent.length))} attempt(s), oldest first</p>
        </div>
      </div>
      <div class="card__body">
        ${sparkChart(
          trend.map((attempt) => ({
            label: formatRelativeTime(attempt.created_at).replace(' ago', ''),
            value: attempt.percentage,
          })),
        )}
      </div>
    </section>

    <div class="chart-grid chart-grid--halves">
      <section class="card">
        <div class="card__header">
          <div>
            <h2 class="card__title">Topic performance</h2>
            <p class="card__subtitle">Average score per topic, strongest first</p>
          </div>
        </div>
        <div class="card__body">
          ${
            topics.length
              ? barList(
                  topics.slice(0, 10).map((topic) => ({
                    label: topic.topic,
                    value: topic.average_percentage,
                    meta: `${topic.attempts} attempt(s) &middot; best ${formatPercent(topic.highest_percentage, 0)} &middot; ${topic.questions_answered} question(s)`.replace(
                      /&middot;/g,
                      '·',
                    ),
                    tone: toneForScore(topic.average_percentage),
                  })),
                )
              : '<p class="field__hint">No topic-level results yet.</p>'
          }
        </div>
      </section>

      <section class="card">
        <div class="card__header">
          <div>
            <h2 class="card__title">Score distribution</h2>
            <p class="card__subtitle">How your topics fall into performance bands</p>
          </div>
        </div>
        <div class="card__body">
          ${donutChart(
            distribution
              .filter((band) => band.topics > 0)
              .map((band, index) => ({
                label: band.band,
                value: band.topics,
                color: [CHART_COLORS.success, CHART_COLORS.info, CHART_COLORS.warning, CHART_COLORS.danger][
                  index
                ],
              })),
            { centerLabel: 'Topics' },
          )}
        </div>
      </section>
    </div>

    <section class="card">
      <div class="card__header">
        <div>
          <h2 class="card__title">Recent attempts</h2>
          <p class="card__subtitle">The most recent graded submissions</p>
        </div>
      </div>
      <div class="card__body card__body--flush">
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr><th>Assessment</th><th>Topic</th><th>Score</th><th>Correct</th><th>Time</th><th>When</th></tr>
            </thead>
            <tbody>
              ${recent
                .map(
                  (attempt) => `
                <tr>
                  <td>
                    <a href="#/result/${encodeURIComponent(attempt.attempt_id)}">
                      ${escapeHtml(attempt.quiz_title || 'Assessment')}
                    </a>
                  </td>
                  <td>${escapeHtml(attempt.topic || 'Full document')}</td>
                  <td class="is-numeric">${escapeHtml(formatPercent(attempt.percentage, 0))}</td>
                  <td class="is-numeric">${escapeHtml(String(attempt.correct_answers))}/${escapeHtml(String(attempt.total_questions))}</td>
                  <td class="is-numeric">&mdash;</td>
                  <td>${escapeHtml(formatRelativeTime(attempt.created_at))}</td>
                </tr>`,
                )
                .join('')}
            </tbody>
          </table>
        </div>
      </div>
    </section>

    ${
      weakestTopic(topics)
        ? `<div class="alert alert--warning">
             <span class="alert__icon" data-icon-slot="bulb"></span>
             <div class="alert__body">
               <p class="alert__title">Where to focus next</p>
               ${escapeHtml(weakestTopic(topics))}
             </div>
           </div>`
        : ''
    }`;

  return {
    title: 'Performance',
    breadcrumb: 'Real analytics from your attempts',
    content,
    mount(root) {
      hydrateIcons(root, icon);
    },
  };
}

function tile(iconName, value, label, tone = 'default', trend = '') {
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

function weakestTopic(topics) {
  if (!topics?.length) return '';
  const weakest = [...topics].sort(
    (a, b) => (a.average_percentage || 0) - (b.average_percentage || 0),
  )[0];
  if (!weakest || (weakest.average_percentage || 0) >= 70) return '';

  return `Your lowest scoring topic is "${weakest.topic}" at ${formatPercent(
    weakest.average_percentage,
    0,
  )} across ${weakest.attempts} attempt(s). Generate a study pack for it, then retake the assessment.`;
}