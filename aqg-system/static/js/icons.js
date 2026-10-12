/**
 * AQG — inline SVG icon set.
 *
 * Icons are declared as raw SVG path markup and injected into the DOM, which
 * keeps the UI dependency-free and lets every glyph inherit `currentColor`.
 * A single `<svg>` sprite sheet is injected once on first use.
 */

const ICONS = {
  dashboard: '<path d="M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z"/>',
  generate: '<path d="M12 3v2M12 19v2M5 12H3M21 12h-2M6.3 6.3 4.9 4.9M19.1 19.1l-1.4-1.4M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/><circle cx="12" cy="12" r="3.2"/>',
  study: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H11v16H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M20 5.5A2.5 2.5 0 0 0 17.5 3H13v16h4.5a2.5 2.5 0 0 1 2.5 2.5z"/>',
  history: '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3 4v4h4"/><path d="M12 7.5V12l3 1.8"/>',
  assessment: '<path d="M8 4h8a2 2 0 0 1 2 2v13a1 1 0 0 1-1.5.9L12 17l-4.5 2.9A1 1 0 0 1 6 19V6a2 2 0 0 1 2-2z"/><path d="m9.2 11.2 1.9 1.9 3.8-3.8"/>',
  performance: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 9 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.6 9a2.5 2.5 0 1 1 3.6 2.2c-.8.5-1.2 1-1.2 2"/><path d="M12 17h.01"/>',
  api: '<path d="M8 8-4 12l4 4M16 8l4 4-4 4M13.5 5l-3 14"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 13.2A8.6 8.6 0 1 1 10.8 3a6.9 6.9 0 0 0 10.2 10.2z"/>',
  menu: '<path d="M3 6h18M3 12h18M3 18h18"/>',
  close: '<path d="M18 6 6 18M6 6l12 12"/>',
  chevronLeft: '<path d="m15 18-6-6 6-6"/>',
  chevronRight: '<path d="m9 18 6-6-6-6"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7.5 8.5 4.5-4.5 4.5 4.5"/><path d="M12 4v12"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  fileText: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6"/><path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7"/>',
  checkCircle: '<circle cx="12" cy="12" r="9"/><path d="m8.5 12.2 2.4 2.4 4.6-4.9"/>',
  xCircle: '<circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/>',
  alert: '<path d="M12 3.5 2.8 19.5h18.4z"/><path d="M12 10v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  sparkle: '<path d="m12 3 1.9 4.6L18.5 9.5 13.9 11.4 12 16l-1.9-4.6L5.5 9.5l4.6-1.9z"/><path d="m18.5 15.5.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9z"/>',
  cards: '<rect x="3" y="6" width="13" height="15" rx="2"/><path d="M7 3h11a2 2 0 0 1 2 2v11"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.2l3.2 1.9"/>',
  target: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1"/>',
  trending: '<path d="m3 16 5.5-5.5 3.5 3.5L21 5"/><path d="M15 5h6v6"/>',
  award: '<circle cx="12" cy="9" r="5.5"/><path d="m8.5 13.5-1.5 8 5-2.5 5 2.5-1.5-8"/>',
  book: '<path d="M5 4.5A1.5 1.5 0 0 1 6.5 3H19v18H6.5A1.5 1.5 0 0 1 5 19.5z"/><path d="M9 3v18"/>',
  refresh: '<path d="M20.5 12a8.5 8.5 0 1 1-2.5-6"/><path d="M20.5 4v5h-5"/>',
  logout: '<path d="M9 20H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h3"/><path d="M15 16l4-4-4-4M19 12H9"/>',
  bell: '<path d="M18 8.5a6 6 0 1 0-12 0c0 5-2 6.5-2 6.5h16s-2-1.5-2-6.5"/><path d="M13.7 19a2 2 0 0 1-3.4 0"/>',
  print: '<path d="M7 8V3h10v5"/><path d="M7 18H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2"/><path d="M7 14h10v7H7z"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  bulb: '<path d="M9.5 18h5M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2h5c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z"/>',
  scale: '<path d="M12 3v18M7 6h10"/><path d="m7 6-3 6a3 3 0 0 0 6 0zM17 6l-3 6a3 3 0 0 0 6 0z"/>',
  quiz: '<path d="M5 4h9l5 5v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"/><path d="M14 4v5h5"/><path d="m8.5 13 1.8 1.8 3.4-3.4"/>',
  summary: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M9 12h6M9 16h4"/>',
  scenario: '<path d="M3 20h18"/><path d="M5 20V9.5L12 4l7 5.5V20"/><path d="M10 20v-5h4v5"/>',
  play: '<path d="M7 4.5 19 12 7 19.5z"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  arrowRight: '<path d="M4 12h16M14 6l6 6-6 6"/>',
  externalLink: '<path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  database: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M10 3v3M14 3v3M10 18v3M14 18v3M3 10h3M3 14h3M18 10h3M18 14h3"/>',
  shield: '<path d="M12 3 5 6v5.5c0 4.3 2.9 8.2 7 9.5 4.1-1.3 7-5.2 7-9.5V6z"/><path d="m9 12 2 2 4-4"/>',
  inbox: '<path d="M3 13h5l1.5 3h5L16 13h5"/><path d="M4.6 5.3 3 13v6a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-6l-1.6-7.7A2 2 0 0 0 17.5 4h-11a2 2 0 0 0-1.9 1.3z"/>',
  zap: '<path d="M13 2 4 14h6l-1 8 9-12h-6z"/>',
  grid: '<rect x="3" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5"/>',
  minus: '<path d="M5 12h14"/>',
};

const SPRITE_ID = 'aqg-icon-sprite';

/** Injects the sprite sheet exactly once. */
function ensureSprite() {
  if (document.getElementById(SPRITE_ID)) return;

  const symbols = Object.entries(ICONS)
    .map(
      ([name, body]) =>
        `<symbol id="icon-${name}" viewBox="0 0 24 24">${body}</symbol>`,
    )
    .join('');

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('id', SPRITE_ID);
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('style', 'position:absolute;width:0;height:0;overflow:hidden');
  svg.innerHTML = symbols;
  document.body.prepend(svg);
}

/**
 * Returns an SVG string for the named icon.
 *
 * @param {string} name Icon key from the ICONS map.
 * @param {{size?: number, className?: string, label?: string}} [options]
 * @returns {string} Safe SVG markup; empty string for an unknown icon.
 */
export function icon(name, options = {}) {
  if (!ICONS[name]) return '';

  const { size = 20, className = '', label = '' } = options;
  ensureSprite();

  const a11y = label
    ? `role="img" aria-label="${escapeAttr(label)}"`
    : 'aria-hidden="true" focusable="false"';

  return `<svg class="${escapeAttr(className)}" width="${size}" height="${size}" ${a11y}><use href="#icon-${name}"></use></svg>`;
}

function escapeAttr(value) {
  return String(value ?? '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

export const ICON_NAMES = Object.keys(ICONS);