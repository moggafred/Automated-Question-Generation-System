/**
 * Thin API client for the AQG backend.
 *
 * Every response is JSON. Domain failures arrive as `{error, detail}` with a
 * meaningful status code, so `ApiError` carries an end-user-safe message that
 * pages can render verbatim.
 */

const BASE = '/api';

/** Name of the readable, CSRF double-submit cookie set by the backend. */
const CSRF_COOKIE = 'aqg_csrf';

/** Methods that mutate state and therefore must carry the CSRF token. */
const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/** Reads a cookie value by name; returns '' when absent. */
function readCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : '';
}

/** Broadcasts that the session is no longer valid so the shell can re-gate. */
function signalUnauthenticated() {
  window.dispatchEvent(new CustomEvent('aqg:unauthorized'));
}

/** Error thrown for any non-2xx response, carrying a user-safe message. */
export class ApiError extends Error {
  constructor(message, { status = 0, code = 'request_failed', payload = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.payload = payload;
  }

  /** True when the resource was not found. */
  get isNotFound() {
    return this.status === 404;
  }

  /** True when the upload or request exceeded a server-side limit. */
  get isLimitExceeded() {
    return this.status === 413 || this.status === 429;
  }
}

/** Error thrown when a request is aborted or the network is unavailable. */
export class NetworkError extends Error {
  constructor(message = 'We could not reach the server. Check your connection and try again.') {
    super(message);
    this.name = 'NetworkError';
    this.status = 0;
    this.code = 'network_error';
  }

  get isNotFound() {
    return false;
  }

  get isLimitExceeded() {
    return false;
  }
}

async function request(${BASE}path, { method = 'GET', body, form, signal } = {}) {
  // Credentials must travel with every call so the session cookie is sent,
  // including when the SPA is served from a different origin than the API.
  const init = { method, signal, credentials: 'include', headers: { Accept: 'application/json' } };

  if (form) {
    init.body = form; // Let the browser set the multipart boundary.
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }

  // Double-submit CSRF token for state-changing requests.
  if (MUTATING.has(method)) {
    const token = readCookie(CSRF_COOKIE);
    if (token) init.headers['X-CSRF-Token'] = token;
  }

  let response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    if (error?.name === 'AbortError') throw error;
    throw new NetworkError();
  }

  const isJson = (response.headers.get('content-type') || '').includes('application/json');
  const payload = isJson ? await response.json().catch(() => null) : null;

  if (!response.ok) {
    // A 401 outside the auth endpoints means the session expired: let the shell
    // tear down protected UI. Auth calls handle their own 401s inline.
    if (response.status === 401 && !path.startsWith(`${BASE}/auth/`)) {
      signalUnauthenticated();
    }
    throw new ApiError(errorMessage(payload, response.status), {
      status: response.status,
      code: payload?.error || 'request_failed',
      payload,
    });
  }

  return payload;
}

/** Picks a renderable message out of an error payload of any known shape. */
function errorMessage(payload, status) {
  const detail = payload?.detail;

  if (typeof detail === 'string' && detail.trim()) return detail;

  // FastAPI's raw validation payload arrives as a list of field errors.
  if (Array.isArray(detail)) {
    const named = detail
      .map((item) => String(item?.loc?.filter((part) => part !== 'body').join('.') || ''))
      .filter(Boolean);
    return named.length
      ? `Please check: ${named.join(', ')}.`
      : 'The request could not be processed.';
  }

  if (typeof payload?.message === 'string' && payload.message.trim()) return payload.message;

  return defaultMessageForStatus(status);
}

function defaultMessageForStatus(status) {
  if (status === 404) return 'We could not find that record.';
  if (status === 413) return 'That file is larger than the maximum upload size.';
  if (status === 429) return 'Too many requests. Please wait a moment and try again.';
  if (status >= 500) return 'The server had a problem. Please try again.';
  return 'The request could not be completed.';
}

function query(params = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    search.set(key, String(value));
  }
  const serialized = search.toString();
  return serialized ? `?${serialized}` : '';
}

// -- Authentication ------------------------------------------------------

export function getAuthProviders(options) {
  return request(${BASE}`${BASE}/auth/providers`, options);
}

export function getCurrentUser(options) {
  return request(${BASE}`${BASE}/auth/me`, options);
}

export function registerAccount(payload, options) {
  return request(${BASE}`${BASE}/auth/register`, { method: 'POST', body: payload, ...options });
}

export function loginWithPassword(payload, options) {
  return request(${BASE}`${BASE}/auth/login`, { method: 'POST', body: payload, ...options });
}

export function logout(options) {
  return request(${BASE}`${BASE}/auth/logout`, { method: 'POST', ...options });
}

export function logoutEverywhere(options) {
  return request(${BASE}`${BASE}/auth/logout-all`, { method: 'POST', ...options });
}

export function updateProfile(payload, options) {
  return request(${BASE}`${BASE}/auth/profile`, { method: 'PATCH', body: payload, ...options });
}

export function startGoogleSignIn(next = '', options) {
  return request(${BASE}`${BASE}/auth/google/start${query({ next })}`, options);
}

// -- System --------------------------------------------------------------

export function getStatus(options) {
  return request(${BASE}`${BASE}/status`, options);
}

export function getDashboard(options) {
  return request(${BASE}`${BASE}/dashboard`, options);
}

export function getLimits(options) {
  return request(${BASE}`${BASE}/limits`, options);
}

// -- Documents -----------------------------------------------------------

export function listDocuments(params = {}, options) {
  return request(${BASE}`${BASE}/documents${query(params)}`, options);
}

// -- Generation ----------------------------------------------------------

/**
 * Generates a grounded assessment from an uploaded document.
 *
 * @param {File} file PDF or TXT learning material.
 * @param {{type?: string, count?: number, difficulty?: string, topic?: string, instructions?: string}} config
 */
export function generateQuiz(file, config = {}, options) {
  const form = new FormData();
  form.append('file', file, file.name);
  form.append('type', config.type || 'multiple-choice');
  form.append('count', String(config.count ?? 5));
  form.append('difficulty', config.difficulty || 'medium');
  form.append('topic', config.topic || '');
  form.append('instructions', config.instructions || '');
  return request(${BASE}`${BASE}/generate-quiz`, { method: 'POST', form, ...options });
}

// -- Study materials -----------------------------------------------------

export function generateStudyMaterial(file, config = {}, options) {
  const form = new FormData();
  form.append('file', file, file.name);
  form.append('type', config.type || 'all');
  form.append('topic', config.topic || '');
  return request(${BASE}`${BASE}/generate-study-material`, { method: 'POST', form, ...options });
}

export function listStudyMaterials(params = {}, options) {
  return request(${BASE}`${BASE}/study-materials${query(params)}`, options);
}

export function getStudyMaterial(materialId, options) {
  return request(${BASE}`${BASE}/study-materials/${encodeURIComponent(materialId)}`, options);
}

export function deleteStudyMaterial(materialId, options) {
  return request(${BASE}`${BASE}/study-materials/${encodeURIComponent(materialId)}`, {
    method: 'DELETE',
    ...options,
  });
}

export function getStudyTypes(options) {
  return request(${BASE}`${BASE}/study-types`, options);
}

// -- Quizzes -------------------------------------------------------------

export function getQuiz(quizId, options) {
  return request(${BASE}`${BASE}/quiz/${encodeURIComponent(quizId)}`, options);
}

export function listQuizzes(params = {}, options) {
  return request(${BASE}`${BASE}/quizzes${query(params)}`, options);
}

export function deleteQuiz(quizId, options) {
  return request(${BASE}`${BASE}/v1/quizzes/${encodeURIComponent(quizId)}`, { method: 'DELETE', ...options });
}

// -- Assessments ---------------------------------------------------------

export function submitAssessment(quizId, submission, options) {
  return request(${BASE}`${BASE}/assessment/${encodeURIComponent(quizId)}/submit`, {
    method: 'POST',
    body: submission,
    ...options,
  });
}

export function listAttempts(params = {}, options) {
  return request(${BASE}`${BASE}/assessment/history${query(params)}`, options);
}

export function getAttempt(attemptId, options) {
  return request(${BASE}`${BASE}/assessment/attempts/${encodeURIComponent(attemptId)}`, options);
}

export function getAttemptTypes(options) {
  return request(${BASE}`${BASE}/assessment-types`, options);
}

// -- Performance ---------------------------------------------------------

export function getPerformance(options) {
  return request(${BASE}`${BASE}/performance`, options);
}
export function googleGuestSignIn(payload, options) {
  return request(${BASE}${BASE}/auth/google/guest, { method: 'POST', body: payload, ...options });
}


export function googleGuestSignIn(payload, options) {
  return request(${BASE}/auth/google/guest, { method: 'POST', body: payload, ...options });
}

