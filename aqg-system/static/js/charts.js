/**
 * Lightweight, dependency-free visualisations.
 *
 * Everything is plain SVG or CSS so charts inherit the active theme and stay
 * printable without a charting library.
 */

import { escapeHtml, formatPercent, progressBar } from './dom.js';

/**
 * Horizontal bar list used for topic accuracy and question-type breakdowns.
 *
 * @param {Array<{label: string, value: number, meta?: string, tone?: string}>} rows
 */
export function barList(rows) {
  if (!rows?.length) return '';

  return `
    <div class="bar-list">
      ${rows
        .map(
          (row) => `
          <div class="bar-row">
            <div class="bar-row__head">
              <span class="bar-row__label" title="${escapeHtml(row.label)}">${escapeHtml(row.label)}</span>
              <span class="bar-row__value">${escapeHtml(row.display ?? formatPercent(row.value, 0))}</span>
            </div>
            ${progressBar(row.value, row.tone)}
            ${row.meta ? `<span class="bar-row__meta">${escapeHtml(row.meta)}</span>` : ''}
          </div>`,
        )
        .join('')}
    </div>`;
}

/**
 * Vertical bar chart for score history.
 *
 * @param {Array<{label: string, value: number}>} points
 */
export function sparkChart(points) {
  if (!points?.length) return '';

  return `
    <div class="spark">
      ${points
        .map((point) => {
          const value = Math.max(0, Math.min(100, Number(point.value) || 0));
          const height = Math.max(4, Math.round(value * 1.2));
          return `
            <div class="spark__bar">
              <div class="spark__fill" data-value="${value.toFixed(0)}" style="height:${height}px" title="${escapeHtml(point.label)}: ${formatPercent(value, 0)}"></div>
              <span class="spark__caption">${escapeHtml(point.label)}</span>
            </div>`;
        })
        .join('')}
    </div>`;
}

/**
 * Donut chart with a legend.
 *
 * @param {Array<{label: string, value: number, color?: string}>} slices
 * @param {{centerValue?: string, centerLabel?: string}} [options]
 */
export function donutChart(slices, options = {}) {
  const total = slices.reduce((sum, slice) => sum + (Number(slice.value) || 0), 0);

  if (!total) {
    return `<div class="state"><p class="state__text">No distribution data yet.</p></div>`;
  }

  const radius = 68;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  const rings = slices
    .map((slice) => {
      const fraction = (Number(slice.value) || 0) / total;
      const dash = fraction * circumference;
      const segment = `
        <circle
          cx="84" cy="84" r="${radius}"
          fill="none"
          stroke="${escapeHtml(slice.color || 'var(--primary)')}"
          stroke-width="18"
          stroke-dasharray="${dash.toFixed(2)} ${(circumference - dash).toFixed(2)}"
          stroke-dashoffset="${(-offset).toFixed(2)}"
        />`;
      offset += dash;
      return segment;
    })
    .join('');

  return `
    <div class="donut">
      <div class="donut__chart">
        <svg viewBox="0 0 168 168" aria-hidden="true">
          <circle cx="84" cy="84" r="${radius}" fill="none" stroke="var(--surface-sunken)" stroke-width="18" />
          ${rings}
        </svg>
        <div class="donut__center">
          <p class="donut__value">${escapeHtml(options.centerValue ?? total)}</p>
          <p class="donut__label">${escapeHtml(options.centerLabel ?? 'Total')}</p>
        </div>
      </div>
      <div class="donut__legend">
        ${slices
          .map(
            (slice) => `
            <div class="donut__legend-row">
              <span class="donut__swatch" style="background:${escapeHtml(slice.color || 'var(--primary)')}"></span>
              <span class="donut__legend-label">${escapeHtml(slice.label)}</span>
              <span class="donut__legend-value">${escapeHtml(String(slice.value))}</span>
            </div>`,
          )
          .join('')}
      </div>
    </div>`;
}

/**
 * Circular score gauge for the result screen.
 *
 * @param {number} percentage 0-100
 */
export function scoreRing(percentage) {
  const value = Math.max(0, Math.min(100, Number(percentage) || 0));
  const radius = 78;
  const circumference = 2 * Math.PI * radius;
  const dash = (value / 100) * circumference;

  return `
    <div class="score-ring">
      <svg viewBox="0 0 180 180" aria-hidden="true">
        <circle class="score-ring__track" cx="90" cy="90" r="${radius}" />
        <circle
          class="score-ring__value"
          cx="90" cy="90" r="${radius}"
          stroke-dasharray="${circumference.toFixed(2)}"
          stroke-dashoffset="${(circumference - dash).toFixed(2)}"
        />
      </svg>
      <div class="score-ring__inner">
        <p class="score-ring__percent">${value.toFixed(0)}%</p>
        <p class="score-ring__fraction" data-role="fraction"></p>
      </div>
    </div>`;
}

/** Palette used by the donut and spark charts. */
export const CHART_COLORS = {
  primary: 'var(--primary)',
  success: 'var(--success-600)',
  warning: 'var(--warning-600)',
  danger: 'var(--danger-600)',
  info: 'var(--info-600)',
  accent: 'var(--accent-500)',
  neutral: 'var(--border-strong)',
};