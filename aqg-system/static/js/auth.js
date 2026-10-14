/**
 * Authentication client: session state, the sign-in gate and the account menu.
 *
 * The backend is the source of truth -- this module only mirrors the resolved
 * principal for rendering, and never decides access on its own. When the API
 * reports a 401 (see `api.js`) the shell re-gates via the `aqg:unauthorized`
 * event.
 */

import {
  ApiError,
  getAuthProviders,
  getCurrentUser as fetchCurrentUser,
  loginWithPassword,
  logout as requestLogout,
  logoutEverywhere as requestLogoutEverywhere,
  registerAccount,
  startGoogleSignIn,
} from './api.js';
import { $, escapeHtml, hydrateIcons } from './dom.js';
import { icon } from './icons.js';
import { toastSuccess } from './toast.js';

let currentUser = null;
let providerState = { google: false, emailPassword: true, configured: false };

const OAUTH_ERROR_MESSAGES = {
  google_failed: 'Google sign-in could not be completed. Please try again.',
  google_cancelled: 'Google sign-in was cancelled.',
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

/** Turns an OAuth redirect code into a message the gate can display. */
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

  currentUser = userPayload?.user ?? null;
  return { providers: getProviders(), user: currentUser };
}

// -- Presentation helpers ------------------------------------------------

/** A friendly label for a user: full name, else the email local part. */
export function displayName(user = currentUser) {
  if (!user) return 'Account';
  const name = String(user.full_name || '').trim();
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

// -- Sign-in gate --------------------------------------------------------

/**
 * Renders the full-screen sign-in gate into `container`.
 *
 * @param {HTMLElement} container
 * @param {{message?: string}} [options]
 */
export function renderGate(container, options = {}) {
  const { google, emailPassword, configured } = providerState;
  const message = options.message || '';

  const noMethods = !google && !emailPassword;

  container.innerHTML = `
    <div class="auth-gate__panel" role="dialog" aria-labelledby="auth-title">
      <div class="auth-gate__aside">
        <div class="auth-gate__brand">
          <span class="auth-gate__logo" data-icon-slot="sparkle" aria-hidden="true"></span>
          <span class="auth-gate__wordmark">
            <span class="auth-gate__name" data-app-name>AQG</span>
            <span class="auth-gate__tagline">Assessment &amp; Study</span>
          </span>
        </div>
        <p class="auth-gate__pitch">
          Turn any document into grounded assessments, study material and real performance
          insight -- powered by retrieval-augmented AI.
        </p>
        <ul class="auth-gate__points">
          <li><span data-icon-slot="shield" aria-hidden="true"></span> Your material stays private to your account</li>
          <li><span data-icon-slot="sparkle" aria-hidden="true"></span> Questions grounded in the source, every time</li>
          <li><span data-icon-slot="trending" aria-hidden="true"></span> Track progress across every attempt</li>
        </ul>
      </div>

      <div class="auth-gate__body">
        <div class="auth-gate__heading">
          <h1 class="auth-gate__title" id="auth-title">Welcome back</h1>
          <p class="auth-gate__subtitle" id="auth-subtitle">Sign in to continue to your workspace.</p>
        </div>

        ${message ? `<div class="auth-gate__alert" role="alert"><span data-icon-slot="alert" aria-hidden="true"></span><span>${escapeHtml(message)}</span></div>` : ''}

        ${
          noMethods
            ? `<div class="auth-gate__alert" role="alert"><span data-icon-slot="info" aria-hidden="true"></span><span>Sign-in is not configured on this deployment. Please contact the administrator.</span></div>`
            : ''
        }

        ${
          emailPassword
            ? `
        <div class="auth-gate__tabs" role="tablist" aria-label="Sign in or create an account">
          <button type="button" class="auth-gate__tab" role="tab" data-mode="login" aria-selected="true">Sign in</button>
          <button type="button" class="auth-gate__tab" role="tab" data-mode="register" aria-selected="false">Create account</button>
        </div>

        <form class="auth-gate__form" id="auth-form" novalidate>
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
          <button type="submit" class="btn btn--primary btn--lg btn--block" id="auth-submit">Sign in</button>
        </form>`
            : ''
        }

        ${
          google && emailPassword
            ? '<div class="auth-gate__divider"><span>or</span></div>'
            : ''
        }

        ${
          google
            ? `
        <button type="button" class="btn btn--secondary btn--lg btn--block auth-gate__google" id="auth-google">
          <span data-icon-slot="google" aria-hidden="true"></span><span>Continue with Google</span>
        </button>`
            : ''
        }

        <p class="auth-gate__legal">
          By continuing you agree to use this platform responsibly. We store only what you create
          and never share it with third parties.
        </p>
      </div>
    </div>`;

  hydrateIcons(container, icon);

  const form = container.querySelector('#auth-form');
  const errorNode = container.querySelector('#auth-error');
  const submit = container.querySelector('#auth-submit');
  const title = container.querySelector('#auth-title');
  const subtitle = container.querySelector('#auth-subtitle');
  const tabs = Array.from(container.querySelectorAll('.auth-gate__tab'));
  const registerFields = Array.from(container.querySelectorAll('[data-register-only]'));

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
    if (title) title.textContent = isRegister ? 'Create your account' : 'Welcome back';
    if (subtitle) {
      subtitle.textContent = isRegister
        ? 'Start turning your material into assessments in seconds.'
        : 'Sign in to continue to your workspace.';
    }
    if (submit) submit.textContent = isRegister ? 'Create account' : 'Sign in';

    const password = container.querySelector('#auth-password');
    if (password) password.setAttribute('autocomplete', isRegister ? 'new-password' : 'current-password');

    showError('');
  };

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
        if (password.length < 8) {
          showError('Choose a password with at least 8 characters.');
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
          await registerAccount({ email, password, full_name: fullName });
        } else {
          await loginWithPassword({ email, password });
        }
        window.location.reload();
      } catch (error) {
        showError(safeMessage(error));
        setBusy(submit, false);
      }
    });
  }

  const googleButton = container.querySelector('#auth-google');
  if (googleButton) {
    googleButton.addEventListener('click', async () => {
      setBusy(googleButton, true);
      try {
        const { authorization_url: url } = await startGoogleSignIn();
        if (!url) throw new Error('The provider did not return a sign-in URL.');
        window.location.assign(url);
      } catch (error) {
        showError(safeMessage(error));
        setBusy(googleButton, false);
      }
    });
  }

  applyMode('login');
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
    const picture = String(user.picture_url || '').trim();
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
          user.picture_url
            ? `<img src="${escapeHtml(user.picture_url)}" alt="" referrerpolicy="no-referrer" />`
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

/** Runs a logout request, then reloads so the shell re-gates cleanly. */
async function endSession(request, message) {
  try {
    await request();
  } catch (error) {
    // A failed logout should not trap the user; the gate will still appear.
    console.warn('Sign-out request failed:', error);
  }
  currentUser = null;
  toastSuccess(message);
  window.setTimeout(() => window.location.reload(), 400);
}

/** Clears local state and shows a message; used when the session expires. */
export function expireSession() {
  currentUser = null;
}
