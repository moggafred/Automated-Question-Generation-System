/**
 * AQG application entry point.
 *
 * Boots the shell (icons, theme, navigation state, status indicator) and hands
 * page rendering to the hash router. Pages are lazily imported on navigation.
 */

import { getStatus } from './api.js';
import { $, debounce, hydrateIcons } from './dom.js';
import { icon } from './icons.js';
import { parseHash, start as startRouter } from './router.js';
import {
  getTheme,
  isSidebarCollapsed,
  setSidebarCollapsed,
  setStatus,
  toggleTheme,
} from './store.js';
import { toastError } from './toast.js';
import {
  applyUserToChrome,
  loadAuth,
  mountUserMenu,
  oauthErrorMessage,
  renderGate,
} from './auth.js';

const NAV_SELECTOR = '[data-nav]';

// -- Shell chrome ---------------------------------------------------------

/** Fills every `[data-icon-slot]` in the static shell markup. */
function hydrateShell() {
  hydrateIcons(document, icon);

  const logo = $('#brand-logo');
  if (logo) logo.innerHTML = icon('sparkle', { size: 22 });
}

function applyBrand(status) {
  const name = status?.app_name || 'AQG';
  const tagline = status?.app_tagline || 'Assessment & Study';

  document.querySelectorAll('[data-app-name]').forEach((node) => {
    node.textContent = name;
  });
  document.querySelectorAll('[data-app-tagline]').forEach((node) => {
    node.textContent = tagline;
  });

  const brand = $('#brand-logo');
  if (brand) brand.textContent = name.slice(0, 2).toUpperCase();
}

/** Highlights the nav item matching the active route. */
function setActiveNav(navKey) {
  document.querySelectorAll(NAV_SELECTOR).forEach((link) => {
    const isActive = Boolean(navKey) && link.dataset.nav === navKey;
    if (isActive) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
}

function syncTopbar(view) {
  const title = $('#page-title');
  const breadcrumb = $('#page-breadcrumb');
  if (title) title.textContent = view.title || 'AQG';
  if (breadcrumb) {
    breadcrumb.textContent = view.breadcrumb || '';
    breadcrumb.hidden = !view.breadcrumb;
  }
  document.title = `${view.title || 'Dashboard'} · AQG`;
  setActiveNav(view.nav);
  closeDrawer();
}

function syncThemeButton() {
  const button = $('#theme-toggle');
  if (!button) return;

  const dark = getTheme() === 'dark';
  button.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
  button.title = dark ? 'Switch to light theme' : 'Switch to dark theme';
  const slot = button.querySelector('[data-icon-slot]');
  if (slot) slot.innerHTML = icon(dark ? 'sun' : 'moon', { size: 20 });
}

function applySidebarState() {
  const shell = $('#app-shell');
  if (!shell) return;

  const collapsed = isSidebarCollapsed();
  shell.dataset.sidebar = collapsed ? 'collapsed' : 'expanded';

  const button = $('#sidebar-collapse');
  const slot = button?.querySelector('[data-icon-slot]');
  if (slot) slot.innerHTML = icon(collapsed ? 'chevronRight' : 'chevronLeft', { size: 20 });
}

// -- Mobile drawer -------------------------------------------------------

function openDrawer() {
  document.body.dataset.drawer = 'open';
  $('#drawer-toggle')?.setAttribute('aria-expanded', 'true');
}

function closeDrawer() {
  if (document.body.dataset.drawer !== 'open') return;
  delete document.body.dataset.drawer;
  $('#drawer-toggle')?.setAttribute('aria-expanded', 'false');
}

// -- Platform status -----------------------------------------------------

function setStatusIndicator(state, text) {
  const node = $('#sidebar-status');
  if (!node) return;

  const dot = node.querySelector('.status-dot');
  if (dot) dot.dataset.state = state;

  const label = node.querySelector('span:last-child');
  if (label) label.textContent = text;
}

async function refreshStatus() {
  setStatusIndicator('pending', 'Checking…');
  try {
    const status = await getStatus();
    setStatus(status);
    applyBrand(status);

    const database = status.services?.database?.status || 'unknown';
    const online = database === 'online';
    setStatusIndicator(online ? 'online' : 'degraded', online ? 'All systems online' : 'Database degraded');
  } catch (error) {
    setStatusIndicator('degraded', 'Server unreachable');
    // Only surface connectivity problems once the user is already in the app.
    if (!document.body.dataset.booted) toastError(error.message);
  }
}

// -- Global search -------------------------------------------------------

function wireGlobalSearch() {
  const input = $('#global-search');
  if (!input) return;

  const run = debounce(() => {
    const term = input.value.trim();
    window.location.hash = term ? `#/history?search=${encodeURIComponent(term)}` : '#/history';
  }, 420);

  input.addEventListener('input', run);
  input.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    const term = input.value.trim();
    window.location.hash = term ? `#/history?search=${encodeURIComponent(term)}` : '#/history';
  });
}

/** Pre-fills the search box when the history page already has a search term. */
function syncSearchWithRoute() {
  const input = $('#global-search');
  if (!input) return;

  const { query } = parseHash();
  input.value = query.search || '';
}

// -- Boot ----------------------------------------------------------------

function wireShellEvents() {
  $('#theme-toggle')?.addEventListener('click', () => {
    toggleTheme();
  });

  document.addEventListener('aqg:themechange', syncThemeButton);

  $('#sidebar-collapse')?.addEventListener('click', () => {
    const shell = $('#app-shell');
    const collapsed = shell?.dataset.sidebar !== 'collapsed';
    if (shell) shell.dataset.sidebar = collapsed ? 'collapsed' : 'expanded';
    setSidebarCollapsed(collapsed);
    const slot = $('#sidebar-collapse')?.querySelector('[data-icon-slot]');
    if (slot) slot.innerHTML = icon(collapsed ? 'chevronRight' : 'chevronLeft', { size: 20 });
  });

  $('#drawer-toggle')?.addEventListener('click', () => {
    if (document.body.dataset.drawer === 'open') closeDrawer();
    else openDrawer();
  });

  $('#sidebar-backdrop')?.addEventListener('click', closeDrawer);

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeDrawer();
  });

  // Close the drawer when a nav link is used on small screens.
  document.querySelectorAll('.sidebar .nav-link').forEach((link) => {
    link.addEventListener('click', closeDrawer);
  });
}

/** Hides the workspace and renders the sign-in gate. */
function showGate(message = '') {
  const shell = $('#app-shell');
  const gate = $('#auth-gate');
  if (shell) shell.dataset.auth = 'signed-out';
  if (gate) {
    gate.hidden = false;
    renderGate(gate, { message });
  }
  document.body.dataset.booted = 'true';
}

/** Reveals the workspace and starts routing for a signed-in user. */
function startApp(user) {
  const shell = $('#app-shell');
  const gate = $('#auth-gate');
  if (shell) shell.dataset.auth = 'signed-in';
  if (gate) gate.hidden = true;

  applyUserToChrome(user);

  startRouter($('#page-root'), (view) => {
    syncTopbar(view);
    syncSearchWithRoute();
    document.body.dataset.booted = 'true';
  });

  refreshStatus();

  // Keep the service indicator honest without hammering the API.
  setInterval(refreshStatus, 120000);
}

/** Strips `?auth_error=...` so a reload does not replay the message. */
function clearOauthErrorParam() {
  const url = new URL(window.location.href);
  if (!url.searchParams.has('auth_error')) return;
  url.searchParams.delete('auth_error');
  const search = url.searchParams.toString();
  history.replaceState(null, '', `${url.pathname}${search ? `?${search}` : ''}${url.hash}`);
}

async function boot() {
  hydrateShell();
  applySidebarState();
  syncThemeButton();
  wireShellEvents();
  wireGlobalSearch();
  mountUserMenu();

  // A session that lapses mid-use returns the user to the gate.
  window.addEventListener('aqg:unauthorized', () => {
    showGate('Your session has expired. Please sign in again.');
  });

  const params = new URLSearchParams(window.location.search);
  const oauthError = params.get('auth_error');

  let state;
  try {
    state = await loadAuth();
  } catch (error) {
    // The server could not be reached; the gate doubles as a status screen.
    showGate('We could not reach the server. Check your connection and try again.');
    if (!document.body.dataset.booted) toastError(error.message);
    return;
  }

  clearOauthErrorParam();

  if (state.user) {
    startApp(state.user);
  } else {
    showGate(oauthErrorMessage(oauthError));
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot, { once: true });
} else {
  boot();
}