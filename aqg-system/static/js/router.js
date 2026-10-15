/**
 * Hash-based router with lazy-loaded page modules.
 *
 * Routes look like `#/generate`, `#/quiz/<id>` or `#/history?search=photosynthesis`.
 * Each page module is dynamically imported on first navigation, then cached, so
 * the initial load only downloads what the dashboard needs.
 *
 * Routes flagged `public: true` render for everyone. Every other route is
 * protected: an unauthenticated visitor is returned to the public dashboard and
 * the sign-in modal opens, remembering the intended destination so the feature
 * resumes right after sign-in.
 */

import { isAuthenticated, openAuthModal, setPendingDestination } from './auth.js';

/**
 * @typedef {object} PageView
 * @property {string} title Top bar title.
 * @property {string} [breadcrumb] Secondary top bar line.
 * @property {string} content HTML for the page container.
 * @property {(root: HTMLElement) => (void|Promise<void>)} [mount] Runs after the content is in the DOM.
 * @property {() => void} [cleanup] Runs before the next navigation.
 */

const ROUTES = [
  {
    path: '/home',
    nav: 'home',
    title: 'AQG',
    breadcrumb: 'AI-powered assessment & study',
    public: true,
    load: () => import('./pages/home.js'),
  },
  {
    path: '/dashboard',
    nav: 'dashboard',
    title: 'Dashboard',
    breadcrumb: 'Overview',
    load: () => import('./pages/dashboard.js'),
  },
  {
    path: '/generate',
    nav: 'generate',
    title: 'Generate Assessment',
    breadcrumb: 'Create from a document',
    load: () => import('./pages/generate.js'),
  },
  {
    path: '/study',
    nav: 'study',
    title: 'Study Materials',
    breadcrumb: 'Learn from your document',
    load: () => import('./pages/study.js'),
  },
  {
    path: '/study/:materialId',
    nav: 'study',
    title: 'Study Material',
    breadcrumb: 'Saved resource',
    load: () => import('./pages/study.js'),
  },
  {
    path: '/quiz/:quizId',
    nav: 'history',
    title: 'Take Assessment',
    breadcrumb: 'Assessment in progress',
    load: () => import('./pages/quiz.js'),
  },
  {
    path: '/result/:attemptId',
    nav: 'history',
    title: 'Assessment Result',
    breadcrumb: 'Graded review',
    load: () => import('./pages/result.js'),
  },
  {
    path: '/history',
    nav: 'history',
    title: 'History',
    breadcrumb: 'Your saved assessments',
    load: () => import('./pages/history.js'),
  },
  {
    path: '/assessments',
    nav: 'assessments',
    title: 'Assessment Attempts',
    breadcrumb: 'Every graded submission',
    load: () => import('./pages/assessments.js'),
  },
  {
    path: '/performance',
    nav: 'performance',
    title: 'Performance',
    breadcrumb: 'Real analytics from your attempts',
    load: () => import('./pages/performance.js'),
  },
  {
    path: '/documents',
    nav: 'documents',
    title: 'Documents',
    breadcrumb: 'Everything you have processed',
    load: () => import('./pages/documents.js'),
  },
  {
    path: '/settings',
    nav: 'settings',
    title: 'Settings',
    breadcrumb: 'Preferences and platform status',
    load: () => import('./pages/settings.js'),
  },
  {
    path: '/help',
    nav: 'help',
    title: 'Help & Guide',
    breadcrumb: 'How the platform works',
    public: true,
    load: () => import('./pages/help.js'),
  },
];

const DEFAULT_ROUTE = '/home';
const moduleCache = new Map();

let current = null;
let container = null;
let onNavigate = () => {};

/** Parses a location hash into a normalised path plus query parameters. */
export function parseHash(hash = window.location.hash) {
  const raw = String(hash || '').replace(/^#/, '');
  const [pathPart, queryPart = ''] = raw.split('?');
  const path = pathPart.startsWith('/') ? pathPart : `/${pathPart}`;
  const query = Object.fromEntries(new URLSearchParams(queryPart));
  const segments = path.split('/').filter(Boolean);
  return { path: `/${segments.join('/')}`, segments, query, raw };
}

/** Builds a hash string from a path and query object. */
export function buildHash(path, query = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    search.set(key, String(value));
  }
  const suffix = search.toString();
  return `#${path}${suffix ? `?${suffix}` : ''}`;
}

/** Matches a path against the route table, returning the params it captured. */
function matchRoute(segments) {
  for (const route of ROUTES) {
    const expected = route.path.split('/').filter(Boolean);
    if (expected.length !== segments.length) continue;

    const params = {};
    let matched = true;
    for (let index = 0; index < expected.length; index += 1) {
      const part = expected[index];
      if (part.startsWith(':')) params[part.slice(1)] = decodeURIComponent(segments[index]);
      else if (part !== segments[index]) {
        matched = false;
        break;
      }
    }
    if (matched) return { route, params };
  }
  return null;
}

async function loadPage(route) {
  if (moduleCache.has(route.path)) return moduleCache.get(route.path);

  const module = await route.load();
  const render = module.default || module.render;
  if (typeof render !== 'function') {
    throw new Error(`Route ${route.path} does not export a default render function.`);
  }

  const cached = { render };
  moduleCache.set(route.path, cached);
  return cached;
}

/** Resolves and renders the route described by the given hash. */
export async function resolve(hash = window.location.hash) {
  const { path, segments, query } = parseHash(hash);

  if (!segments.length) {
    return resolve(buildHash(DEFAULT_ROUTE));
  }

  const matched = matchRoute(segments);
  if (!matched) {
    const notFound = await import('./pages/help.js');
    return {
      title: 'Page not found',
      breadcrumb: 'Unknown route',
      nav: null,
      content: notFound.notFoundView(path),
    };
  }

  const { route, params } = matched;

  // Protected route requested by an anonymous visitor: send them to the public
  // dashboard, open the sign-in modal and remember where they wanted to go.
  if (!route.public && !isAuthenticated()) {
    return await guardProtectedRoute(path, query);
  }

  const { render } = await loadPage(route);

  /** @type {PageView} */
  const view = await render({ params, query, path });
  return {
    title: view.title || route.title,
    breadcrumb: view.breadcrumb || route.breadcrumb,
    nav: route.nav,
    content: view.content,
    mount: view.mount,
    cleanup: view.cleanup,
  };
}

/** Redirects to the public dashboard and opens the sign-in modal. */
async function guardProtectedRoute(path, query) {
  const search = new URLSearchParams(query || {}).toString();
  setPendingDestination(`${path}${search ? `?${search}` : ''}`);

  // Rewrite the URL without firing another hashchange, then render the public
  // dashboard in place of the protected page.
  history.replaceState(null, '', buildHash('/home'));

  const home = ROUTES.find((item) => item.path === '/home');
  const { render } = await loadPage(home);
  const view = await render({ params: {}, query: {}, path: '/home' });

  openAuthModal({ message: 'Sign in to continue to this feature.' });

  return {
    title: view.title || home.title,
    breadcrumb: view.breadcrumb || home.breadcrumb,
    nav: home.nav,
    content: view.content,
    mount: view.mount,
    cleanup: view.cleanup,
  };
}

/** Renders a resolved view into the page container. */
function apply(view) {
  if (current?.cleanup) {
    try {
      current.cleanup();
    } catch {
      /* A failing cleanup must not block navigation. */
    }
  }

  container.innerHTML = view.content;
  container.setAttribute('aria-busy', 'false');

  current = view;
  onNavigate(view);

  if (view.mount) {
    Promise.resolve(view.mount(container)).catch((error) => {
      console.error('Page mount failed:', error);
    });
  }
}

function showFatal(message) {
  container.innerHTML = `
    <div class="card"><div class="card__body">
      <div class="state">
        <span class="state__icon" style="background:var(--danger-50);border-color:var(--danger-200);color:var(--danger-700)">
          <span data-icon-slot="alert" style="display:flex"></span>
        </span>
        <p class="state__title">This page could not be loaded</p>
        <p class="state__text"></p>
        <a class="btn btn--primary" href="#/dashboard">Back to dashboard</a>
      </div>
    </div></div>`;

  const text = container.querySelector('.state__text');
  if (text) text.textContent = message;

  container.setAttribute('aria-busy', 'false');
}

/**
 * Boots the router.
 *
 * @param {HTMLElement} pageContainer Element that receives page content.
 * @param {(view: object) => void} [listener] Called after every render.
 */
export function start(pageContainer, listener) {
  container = pageContainer;
  onNavigate = listener || (() => {});

  if (!window.location.hash) {
    // Signed-in users land on their personalized dashboard; visitors land on
    // the public dashboard and can explore before signing in.
    window.location.replace(buildHash(isAuthenticated() ? '/dashboard' : DEFAULT_ROUTE));
  }

  const handle = async () => {
    container.setAttribute('aria-busy', 'true');
    try {
      apply(await resolve());
    } catch (error) {
      console.error('Navigation failed:', error);
      showFatal(error?.message || 'An unexpected error occurred.');
    }
  };

  window.addEventListener('hashchange', handle);
  handle();
}

/** Navigates to a path, adding to history instead of replacing it. */
export function navigate(path, query = {}) {
  window.location.hash = buildHash(path, query).slice(1);
}

/** True when the given hash path is reachable without signing in. */
export function isPublicHash(hash = window.location.hash) {
  const { segments } = parseHash(hash);
  if (!segments.length) return true;
  const matched = matchRoute(segments);
  if (!matched) return true; // Unknown routes render the public not-found view.
  return Boolean(matched.route.public);
}