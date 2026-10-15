/**
 * AQG application entry point.
 *
 * Boots the shell (icons, theme, navigation state, status indicator) and hands
 * page rendering to the hash router. The public dashboard is always available;
 * authentication is requested lazily, only when a protected feature is used.
 */

import { getStatus } from './api.js';
import { $, debounce, hydrateIcons } from './dom.js';
import { icon } from './icons.js';
import { buildHash, isPublicHash, parseHash, start as startRouter } from './router.js';
import {
  getTheme,
  isRailHidden,
  isSidebarCollapsed,
  setRailHidden,
  setSidebarCollapsed,
  setStatus,
  toggleTheme,
} from './store.js';
import { toastError } from './toast.js';
import {
  applyUserToChrome,
  consumePendingDestination,
  loadAuth,
  mountUserMenu,
  oauthErrorMessage,
  openAuthModal,
} from './auth.js';

const NAV_SELECTOR = '[data-nav]';

// -- Shell chrome ---------------------------------------------------------

/** Fills every `[data-icon-slot]` in the static shell markup. */
function hydrateShell() {
  hydrateIcons(document, icon);
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

/** Reflects the resolved session on the shell so CSS can swap the chrome. */
function applyAuthChrome(user) {
  const shell = $('#app-shell');
  if (shell) shell.dataset.auth = user ? 'signed-in' : 'signed-out';
  if (user) applyUserToChrome(user);
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

// -- Right-hand side panel (rail) ----------------------------------------

/** Applies the remembered rail state to the shell and its toggle button. */
function applyRailState() {
  const shell = $('#app-shell');
  const button = $('#rail-toggle');
  const hidden = isRailHidden();

  if (shell) shell.dataset.rail = hidden ? 'hidden' : 'shown';
  if (!button) return;

  // `aria-pressed` carries the state; the label stays constant so assistive
  // tech announces "Toggle side panel, pressed/unpressed", while the tooltip
  // and icon hint at the action.
  button.setAttribute('aria-pressed', String(!hidden));
  button.title = hidden ? 'Show side panel' : 'Hide side panel';

  const slot = button.querySelector('[data-icon-slot]');
  if (slot) slot.innerHTML = icon(hidden ? 'panelRightOpen' : 'panelRightClose', { size: 20 });
}

/** Reveals the toggle only on pages that actually render a right-hand rail. */
function syncRailToggle() {
  const button = $('#rail-toggle');
  const root = $('#page-root');
  if (button) button.hidden = !(root && root.querySelector('[data-rail]'));
}

/** Toggles the rail and remembers the choice across sessions. */
function toggleRail() {
  setRailHidden(!isRailHidden());
  applyRailState();
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

// -- Authentication entry points -----------------------------------------

/** Opens the modal from the shell's Sign In / Get Started controls. */
function wireAuthActions() {
  document.querySelectorAll('[data-action="sign-in"], [data-action="get-started"]').forEach((node) => {
    node.addEventListener('click', () => {
      closeDrawer();
      openAuthModal({ returnTo: '/dashboard' });
    });
  });
}

/** Turns a stored destination such as `/generate?type=essay` into a hash URL. */
function destinationHash(destination) {
  const clean = destination.startsWith('/') ? destination : `/${destination}`;
  return `#${clean}`;
}

/**
 * Handles a session that lapses mid-use: remember the protected page, return to
 * the public dashboard, then invite the visitor to sign in again.
 */
function handleUnauthorized() {
  const current = window.location.hash;
  if (current && !isPublicHash(current)) {
    const { path, query } = parseHash(current);
    const search = new URLSearchParams(query).toString();
    const destination = `${path}${search ? `?${search}` : ''}`;
    openAuthModal({ message: 'Your session has expired. Please sign in again.', returnTo: destination });
    window.location.hash = buildHash('/home');
    return;
  }
  openAuthModal({ message: 'Your session has expired. Please sign in again.' });
}

// -- Boot ----------------------------------------------------------------

function wireShellEvents() {
  $('#theme-toggle')?.addEventListener('click', () => {
    toggleTheme();
  });

  $('#rail-toggle')?.addEventListener('click', toggleRail);

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

/** Strips `?auth_error=...` so a reload does not replay the message. */
function clearOauthErrorParam() {
  const url = new URL(window.location.href);
  if (!url.searchParams.has('auth_error')) return;
  url.searchParams.delete('auth_error');
  const search = url.searchParams.toString();
  history.replaceState(null, '', `${url.pathname}${search ? `?${search}` : ''}${url.hash}`);
}

/** Applies a remembered destination after a successful sign-in. */
function resumeIntendedDestination() {
  const destination = consumePendingDestination();
  if (!destination) return;
  const target = destinationHash(destination);
  if (window.location.hash === target) return;
  // replaceState keeps this silent; the router renders the resulting hash.
  history.replaceState(null, '', target);
}

function onView(view) {
  syncTopbar(view);
  syncSearchWithRoute();
  syncRailToggle();
  document.body.dataset.booted = 'true';
}

async function boot() {
  hydrateShell();
  applySidebarState();
  applyRailState();
  syncThemeButton();
  wireShellEvents();
  wireGlobalSearch();
  wireAuthActions();
  mountUserMenu();

  // A session that lapses mid-use returns the user to the public dashboard.
  window.addEventListener('aqg:unauthorized', handleUnauthorized);

  const params = new URLSearchParams(window.location.search);
  const oauthError = params.get('auth_error');

  let state;
  try {
    state = await loadAuth();
  } catch (error) {
    // The server could not be reached. The public dashboard still renders and
    // the modal doubles as a connection notice.
    applyAuthChrome(null);
    startRouter($('#page-root'), onView);
    openAuthModal({ message: 'We could not reach the server. Check your connection and try again.' });
    toastError(error.message);
    return;
  }

  clearOauthErrorParam();

  const user = state.user;
  applyAuthChrome(user);

  if (user) {
    resumeIntendedDestination();
  }

  startRouter($('#page-root'), onView);
  refreshStatus();

  // Keep the service indicator honest without hammering the API.
  setInterval(refreshStatus, 120000);

  if (!user && oauthError) {
    openAuthModal({ message: oauthErrorMessage(oauthError) });
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot, { once: true });
} else {
  boot();
}
