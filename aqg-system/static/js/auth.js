/**
 * Authentication client: session state, the sign-in modal and the account menu.
 *
 * The backend is the source of truth -- this module only mirrors the resolved
 * principal for rendering, and never decides access on its own. When the API
 * reports a 401 (see `api.js`) the shell re-opens the sign-in modal via the
 * `aqg:unauthorized` event.
 *
 * Public visitors browse the dashboard freely; the modal is opened on demand
 * when a protected feature is requested, and the intended destination is
 * carried through the sign-in round trip so the user resumes exactly where they
 * were headed.
 */

import {
  ApiError,
  getAuthProviders,
  getCurrentUser as fetchCurrentUser,
  googleSignInUrl,
  loginWithPassword,
  logout as requestLogout,
  logoutEverywhere as requestLogoutEverywhere,
  registerAccount,
} from './api.js';
import { $, escapeHtml, hydrateIcons } from './dom.js';
import { icon } from './icons.js';
import { toastSuccess } from './toast.js';

let currentUser = null;
let providerState = { google: false, emailPassword: true, configured: false };

/** Where the user should land after a successful sign-in (hash-route path). */
const RETURN_TO_STORAGE_KEY = 'aqg.returnTo';
const RETURN_TO_MAX_AGE_MS = 20 * 60 * 1000;

const OAUTH_ERROR_MESSAGES = {
  google_failed: 'Google sign-in could not be completed. Please try again.',
  google_cancelled: 'Google sign-in was cancelled.',
  google_unverified: 'Google could not verify that account. Please try again.',
  google_conflict: 'An account already uses this email. Sign in with your existing method first.',
};

/** Friendly labels so the modal can name the feature the visitor asked for. */
const DESTINATION_LABELS = {
  '/dashboard': 'your dashboard',
  '/generate': 'question generation',
  '/study': 'the study material generator',
  '/history': 'your assessment history',
  '/assessments': 'your assessments',
  '/performance': 'your performance analytics',
  '/documents': 'your documents',
  '/settings': 'your account settings',
};

/** The signed-in principal, or null when signed out. */
export function getActiveUser() {
  return currentUser;
}

/** True once a session has been resolved. */
export function isAuthenticated() {
  return Boolean(currentUser);
}

/** Which sign-in methods the backend currently offers. */
export function getProviders() {
  return { ...providerState };
}

/** Turns an OAuth redirect code into a message the modal can display. */
export function oauthErrorMessage(code) {
  if (!code) return '';
  return OAUTH_ERROR_MESSAGES[code] || 'Sign-in could not be completed. Please try again.';
}

/** Resolves provider availability and the current session in one round trip. */
export async function loadAuth() {
  const [providerPayload, userPayload] = await Promise.all([
    getAuthProviders().catch(() => null),
    fetchCurrentUser().catch((error) => {
      if (error instanceof ApiError && error.status === 401) return null;
      throw error;
    }),
  ]);

  if (providerPayload) {
    providerState = {
      google: Boolean(providerPayload.google_enabled),
      emailPassword: Boolean(providerPayload.email_password_enabled),
      configured: Boolean(providerPayload.auth_configured),
    };
  }

  currentUser = userPayload || null;
  return { providers: getProviders(), user: currentUser };
}

// -- Presentation helpers ------------------------------------------------

/** A friendly label for a user: full name, else the email local part. */
export function displayName(user = currentUser) {
  if (!user) return 'Account';
  const name = String(user.name || '').trim();
  if (name) return name;
  const email = String(user.email || '');
  return email.split('@')[0] || 'Account';
}

/** Up to two initials for the avatar. */
export function initials(user = currentUser) {
  const source = displayName(user).replace(/[^\p{L}\p{N} ]/gu, ' ').trim();
  const parts = source.split(/\s+/).filter(Boolean);
  if (!parts.length) return '?';
  const first = parts[0][0] || '';
  const second = parts.length > 1 ? parts[parts.length - 1][0] || '' : parts[0][1] || '';
  return (first + second).toUpperCase();
}

/** Human label for the sign-in method. */
function providerLabel(provider) {
  return provider === 'google' ? 'Google' : 'Email';
}

// -- Intended-destination tracking ---------------------------------------

/** Normalises any hash route into a leading-slash path like `/generate`. */
function normalisePath(path) {
  const value = String(path || '').trim();
  if (!value) return '';
  const withoutHash = value.startsWith('#') ? value.slice(1) : value;
  return withoutHash.startsWith('/') ? withoutHash : `/${withoutHash}`;
}

/** Remembers where the user wanted to go across the sign-in round trip. */
export function setPendingDestination(path) {
  const clean = normalisePath(path);
  if (!clean) return;
  try {
    sessionStorage.setItem(RETURN_TO_STORAGE_KEY, JSON.stringify({ path: clean, at: Date.now() }));
  } catch {
    /* Private mode: the in-memory fallback below still works for this tab. */
  }
  memoDestination = { path: clean, at: Date.now() };
}

let memoDestination = null;

/** Returns the remembered destination without clearing it, or null. */
export function peekPendingDestination() {
  if (memoDestination) return memoDestination.path;
  try {
    const raw = sessionStorage.getItem(RETURN_TO_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed.path !== 'string') return null;
    if (typeof parsed.at === 'number' && Date.now() - parsed.at > RETURN_TO_MAX_AGE_MS) {
      sessionStorage.removeItem(RETURN_TO_STORAGE_KEY);
      return null;
    }
    return parsed.path;
  } catch {
    return null;
  }
}

/** Returns and clears the remembered destination. */
export function consumePendingDestination() {
  const path = peekPendingDestination();
  clearPendingDestination();
  return path;
}

/** Forgets any remembered destination. */
export function clearPendingDestination() {
  memoDestination = null;
  try {
    sessionStorage.removeItem(RETURN_TO_STORAGE_KEY);
  } catch {
    /* Nothing to clear. */
  }
}

/** Human-readable name of the pending destination, for the modal copy. */
function destinationLabel(path) {
  if (!path) return '';
  const base = path.split('?')[0];
  return DESTINATION_LABELS[base] || 'the requested feature';
}

// -- Sign-in modal -------------------------------------------------------

let lastFocused = null;
let modalKeyHandler = null;

/** True while the sign-in modal is on screen. */
export function isAuthModalOpen() {
  const modal = $('#auth-modal');
  return Boolean(modal && !modal.hidden);
}

/** Closes the sign-in modal and restores focus to the opener. */
export function closeAuthModal() {
  const modal = $('#auth-modal');
  if (modal) {
    modal.hidden = true;
    modal.innerHTML = '';
  }
  delete document.body.dataset.modal;
  if (modalKeyHandler) {
    document.removeEventListener('keydown', modalKeyHandler);
    modalKeyHandler = null;
  }
  if (lastFocused && typeof lastFocused.focus === 'function') {
    lastFocused.focus();
  }
  lastFocused = null;
}

/**
 * Renders and opens the sign-in modal.
 *
 * @param {{message?: string, returnTo?: string, silent?: boolean}} [options]
 *   `returnTo` records the intended destination. When omitted the previously
 *   remembered destination (if any) is kept; otherwise a safe default of the
 *   personalized dashboard is used.
 */
export function openAuthModal(options = {}) {
  const modal = $('#auth-modal');
  if (!modal) return;

  if (typeof options.returnTo === 'string') {
    setPendingDestination(options.returnTo);
  } else if (!peekPendingDestination()) {
    setPendingDestination('/dashboard');
  }

  const destination = peekPendingDestination();
  const { google, emailPassword, configured } = providerState;
  const message = options.message || '';
  const noMethods = !google && !emailPassword;

  const appName = $('[data-app-name]')?.textContent?.trim() || 'AQG';
  const appTagline = $('[data-app-tagline]')?.textContent?.trim() || 'Assessment & Study';

  lastFocused = document.activeElement;

  modal.innerHTML = `
    <div class="auth-modal__backdrop" data-action="close"></div>
    <div class="auth-modal__dialog" role="dialog" aria-modal="true" aria-labelledby="auth-modal-title">
      <button type="button" class="auth-modal__close icon-button" data-action="close" aria-label="Close and return to the dashboard">
        <span data-icon-slot="close" aria-hidden="true"></span>
      </button>

      <div class="auth-modal__brand">
        <span class="auth-modal__logo" aria-hidden="true">${escapeHtml(appName.slice(0, 2).toUpperCase())}</span>
        <span class="auth-modal__wordmark">
          <span class="auth-modal__name">${escapeHtml(appName)}</span>
          <span class="auth-modal__tagline">${escapeHtml(appTagline)}</span>
        </span>
      </div>

      <div class="auth-modal__heading">
        <h1 class="auth-modal__title" id="auth-modal-title">Welcome to ${escapeHtml(appName)}</h1>
        <p class="auth-modal__subtitle">
          Sign in to start generating intelligent questions, quizzes, summaries, flashcards, and
          personalized study materials from your learning documents.
        </p>
      </div>

      ${
        destination
          ? `<p class="auth-modal__intent">
               <span data-icon-slot="arrowRight" aria-hidden="true"></span>
               <span>After signing in you will continue to <strong>${escapeHtml(destinationLabel(destination))}</strong>.</span>
             </p>`
          : ''
      }

      ${message ? `<div class="auth-modal__alert" role="alert"><span data-icon-slot="alert" aria-hidden="true"></span><span>${escapeHtml(message)}</span></div>` : ''}

      ${
        noMethods
          ? `<div class="auth-modal__alert" role="alert"><span data-icon-slot="info" aria-hidden="true"></span><span>Sign-in is not configured on this deployment. Please contact the administrator.</span></div>`
          : ''
      }

      ${
        google
          ? `
      <button type="button" class="btn btn--primary btn--lg btn--block auth-modal__google" id="auth-google">
        <span data-icon-slot="google" aria-hidden="true"></span><span>Continue with Google</span>
      </button>`
          : ''
      }

      ${google && emailPassword ? '<div class="auth-modal__divider"><span>or</span></div>' : ''}

      ${
        emailPassword
          ? `
      <div class="auth-modal__tabs" role="tablist" aria-label="Sign in or create an account">
        <button type="button" class="auth-modal__tab" role="tab" data-mode="login" aria-selected="true">Sign in</button>
        <button type="button" class="auth-modal__tab" role="tab" data-mode="register" aria-selected="false">Create account</button>
      </div>

      <form class="auth-modal__form" id="auth-form" novalidate>
        <div class="field" data-register-only hidden>
          <label class="field__label" for="auth-name">Full name</label>
          <input class="input" id="auth-name" name="full_name" type="text" autocomplete="name" placeholder="Ada Lovelace" />
        </div>
        <div class="field">
          <label class="field__label" for="auth-email">Email</label>
          <input class="input" id="auth-email" name="email" type="email" autocomplete="email" placeholder="you@example.com" required />
        </div>
        <div class="field">
          <label class="field__label" for="auth-password">Password</label>
          <input class="input" id="auth-password" name="password" type="password" autocomplete="current-password" placeholder="••••••••" required />
        </div>
        <div class="field" data-register-only hidden>
          <label class="field__label" for="auth-confirm">Confirm password</label>
          <input class="input" id="auth-confirm" name="confirm" type="password" autocomplete="new-password" placeholder="••••••••" />
        </div>
        <p class="field__error" id="auth-error" role="alert" hidden></p>
        <button type="submit" class="btn btn--secondary btn--block" id="auth-submit">Sign in</button>
      </form>`
          : ''
      }

      <p class="auth-modal__legal">
        <span data-icon-slot="shield" aria-hidden="true"></span>
        <span>
          Your documents and results are private to your account and are never shared with third
          parties. Authentication is secured with Google OAuth 2.0 / OpenID Connect and encrypted
          session cookies.
        </span>
      </p>

      <button type="button" class="btn btn--ghost btn--block" data-action="close">Back to Dashboard</button>
    </div>`;

  hydrateIcons(modal, icon);
  modal.hidden = false;
  document.body.dataset.modal = 'open';

  wireModal(modal);
  modalKeyHandler = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeAuthModal();
    }
  };
  document.addEventListener('keydown', modalKeyHandler);

  // Focus the primary action for keyboard and screen-reader users.
  const first = modal.querySelector('#auth-google') || modal.querySelector('#auth-email') || modal.querySelector('[data-action="close"]');
  first?.focus();
}

/** Wires the freshly-rendered modal's interactive elements. */
function wireModal(modal) {
  const form = modal.querySelector('#auth-form');
  const errorNode = modal.querySelector('#auth-error');
  const submit = modal.querySelector('#auth-submit');
  const title = modal.querySelector('#auth-modal-title');
  const subtitle = modal.querySelector('.auth-modal__subtitle');
  const tabs = Array.from(modal.querySelectorAll('.auth-modal__tab'));
  const registerFields = Array.from(modal.querySelectorAll('[data-register-only]'));

  let mode = 'login';

  const showError = (text) => {
    if (!errorNode) return;
    errorNode.textContent = text || '';
    errorNode.hidden = !text;
  };

  const applyMode = (next) => {
    mode = next;
    tabs.forEach((tab) => tab.setAttribute('aria-selected', String(tab.dataset.mode === next)));
    registerFields.forEach((field) => {
      field.hidden = next !== 'register';
    });

    const isRegister = next === 'register';
    if (title) title.textContent = isRegister ? 'Create your account' : `Welcome to ${getName()}`;
    if (subtitle) {
      subtitle.textContent = isRegister
        ? 'Start turning your learning documents into assessments, summaries and flashcards.'
        : 'Sign in to start generating intelligent questions, quizzes, summaries, flashcards, and personalized study materials from your learning documents.';
    }
    if (submit) submit.textContent = isRegister ? 'Create account' : 'Sign in';

    const password = modal.querySelector('#auth-password');
    if (password) password.setAttribute('autocomplete', isRegister ? 'new-password' : 'current-password');

    showError('');
  };

  modal.querySelectorAll('[data-action="close"]').forEach((node) => {
    node.addEventListener('click', () => closeAuthModal());
  });

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => applyMode(tab.dataset.mode));
  });

  if (form) {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      showError('');

      const email = form.email.value.trim();
      const password = form.password.value;
      const fullName = form.full_name ? form.full_name.value.trim() : '';

      if (!email || !password) {
        showError('Please enter your email and password.');
        return;
      }

      if (mode === 'register') {
        if (password.length < 12) {
          showError('Choose a password with at least 12 characters.');
          return;
        }
        if (password !== form.confirm.value) {
          showError('The two passwords do not match.');
          return;
        }
      }

      setBusy(submit, true);
      try {
        if (mode === 'register') {
          await registerAccount({ name: fullName, email, password });
        } else {
          await loginWithPassword({ email, password });
        }
        // A full reload re-resolves the session and resumes the intended route.
        window.location.reload();
      } catch (error) {
        showError(safeMessage(error));
        setBusy(submit, false);
      }
    });
  }

  const googleButton = modal.querySelector('#auth-google');
  if (googleButton) {
    googleButton.addEventListener('click', () => {
      // Full-page redirect to Google; the callback returns to the SPA origin.
      window.location.assign(googleSignInUrl());
    });
  }

  applyMode('login');
}

function getName() {
  return $('[data-app-name]')?.textContent?.trim() || 'AQG';
}

/** Converts any thrown value into an end-user-safe string. */
function safeMessage(error) {
  if (error instanceof ApiError || error?.name === 'ApiError') return error.message;
  if (error?.name === 'AuthConfigError') return error.message;
  return error?.message || 'Something went wrong. Please try again.';
}

/** Toggles a button's busy state without losing its label. */
function setBusy(button, busy) {
  if (!button) return;
  if (busy) {
    button.dataset.label = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="spinner" aria-hidden="true"></span>';
  } else {
    button.disabled = false;
    if (button.dataset.label) button.innerHTML = button.dataset.label;
  }
}

// -- Account menu --------------------------------------------------------

/** Fills the top-bar account button and its dropdown for the given user. */
export function applyUserToChrome(user = currentUser) {
  if (!user) return;

  const avatar = $('#user-avatar');
  const name = $('#user-name');
  const sub = $('#user-sub');
  const panel = $('#user-menu-panel');

  if (avatar) {
    const picture = String(user.avatar_url || '').trim();
    if (picture) {
      avatar.innerHTML = `<img src="${escapeHtml(picture)}" alt="" referrerpolicy="no-referrer" />`;
    } else {
      avatar.textContent = initials(user);
    }
  }
  if (name) name.textContent = displayName(user);
  if (sub) sub.textContent = user.email || providerLabel(user.provider);

  if (panel) {
    panel.innerHTML = `
      <div class="user-menu__header">
        <span class="avatar avatar--lg">${
          user.avatar_url
            ? `<img src="${escapeHtml(user.avatar_url)}" alt="" referrerpolicy="no-referrer" />`
            : escapeHtml(initials(user))
        }</span>
        <div class="user-menu__identity">
          <p class="user-menu__identity-name">${escapeHtml(displayName(user))}</p>
          <p class="user-menu__identity-email">${escapeHtml(user.email || '')}</p>
          <span class="badge badge--neutral">${escapeHtml(providerLabel(user.provider))} sign-in</span>
        </div>
      </div>
      <a class="user-menu__item" role="menuitem" href="#/settings" data-action="settings">
        <span data-icon-slot="settings" aria-hidden="true"></span><span>Account settings</span>
      </a>
      <div class="user-menu__separator" role="separator"></div>
      <button type="button" class="user-menu__item" role="menuitem" data-action="sign-out">
        <span data-icon-slot="logout" aria-hidden="true"></span><span>Sign out</span>
      </button>
      <button type="button" class="user-menu__item user-menu__item--danger" role="menuitem" data-action="sign-out-all">
        <span data-icon-slot="shield" aria-hidden="true"></span><span>Sign out everywhere</span>
      </button>`;

    hydrateIcons(panel, icon);
  }
}

/** Wires the account dropdown: toggle, outside-click, escape and its actions. */
export function mountUserMenu() {
  const toggle = $('#user-menu-toggle');
  const menu = $('#user-menu');
  const panel = $('#user-menu-panel');
  if (!toggle || !menu || !panel) return;

  const close = () => {
    panel.hidden = true;
    menu.dataset.open = 'false';
    toggle.setAttribute('aria-expanded', 'false');
  };

  const open = () => {
    panel.hidden = false;
    menu.dataset.open = 'true';
    toggle.setAttribute('aria-expanded', 'true');
  };

  toggle.addEventListener('click', (event) => {
    event.stopPropagation();
    if (panel.hidden) open();
    else close();
  });

  document.addEventListener('click', (event) => {
    if (panel.hidden) return;
    if (!menu.contains(event.target)) close();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !panel.hidden) {
      close();
      toggle.focus();
    }
  });

  panel.addEventListener('click', async (event) => {
    const target = event.target.closest('[data-action]');
    if (!target) return;

    const action = target.dataset.action;
    if (action === 'settings') {
      close();
      return; // The anchor's hash navigation takes over.
    }

    close();

    if (action === 'sign-out') {
      await endSession(requestLogout, 'You have been signed out.');
    } else if (action === 'sign-out-all') {
      await endSession(requestLogoutEverywhere, 'Signed out on every device.');
    }
  });
}

/** Runs a logout request, then reloads so the shell re-resolves cleanly. */
async function endSession(request, message) {
  try {
    await request();
  } catch (error) {
    // A failed logout should not trap the user; the shell will still re-resolve.
    console.warn('Sign-out request failed:', error);
  }
  currentUser = null;
  clearPendingDestination();
  toastSuccess(message);
  window.setTimeout(() => window.location.reload(), 400);
}

/** Clears local state and shows a message; used when the session expires. */
export function expireSession() {
  currentUser = null;
}
