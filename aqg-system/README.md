# AQG — AI-Powered Educational Assessment and Study Platform

Turns an uploaded PDF or TXT into grounded assessments, study resources and real
performance analytics. FastAPI backend, SQLite persistence and a responsive
no-build frontend (vanilla ES modules and custom CSS — no framework, no bundler).

## Pipeline

```
upload (.pdf/.txt)
  -> DocumentParserService        text extraction + chunking
  -> DocumentRetriever            hashed bag-of-words TF-IDF, word + bigram features
  -> QuestionGeneratorService     LLM call, JSON-schema output, grounded in retrieved chunks
  -> QuizEvaluationAgent          structure/normalisation guardrail, dedup, option integrity
  -> persistence                  uuid4 tracking ID + SQLite record
  -> HTTP response                questions only, never the answer key
```

Study materials reuse the same retrieval stage through
`services/study_materials.py`.

## What it does

- **Assessments** — nine question formats (`multiple-choice`, `true-false`,
  `short-answer`, `fill-in-the-blank`, `essay`, `scenario`, `case-study`,
  `application`, `mixed`), 1–20 questions, three difficulty levels.
- **Automatic grading** — choice items are matched against the answer key; written
  answers earn partial credit for overlapping key ideas.
- **Study resources** — summaries, key concepts, flashcards, definitions and
  revision notes, stored per document.
- **Analytics** — averages, bands, topic-level performance and score distribution,
  aggregated from stored attempts. With no history every metric is `0` and
  `has_data` is `false`, so the UI shows an empty state instead of invented numbers.
- **Frontend** — dashboard, generator, quiz runner, review, study library, history,
  attempts, performance, documents, settings and help. Light/dark themes, mobile
  drawer, keyboard-navigable, no CDN dependencies.

## Answer key secrecy

The answer key is never sent to the browser before submission:

- `GET /api/quiz/{id}` returns `public_dict()`, which drops `correct_answer`,
  `correct_option_id`, `explanation`, `marking_criteria` **and** each option's
  `is_correct` flag.
- `GET /api/quiz/{id}/answer-key` requires an `attempt_id` that belongs to that
  assessment. Without it the response is `403 answer_key_locked`, so the key cannot
  be read off the network tab.
- Scoring happens server-side; the review screen shows the breakdown after grading.

## Authentication

Sign-in is real and enforced by the backend — the frontend never decides access
on its own. Two methods are supported:

- **Email + password** — hashed with stdlib `hashlib.scrypt` (parameters are
  stored alongside each digest, so the work factor can be raised later). Minimum
  length is `PASSWORD_MIN_LENGTH` (default 8). Disable with
  `EMAIL_PASSWORD_ENABLED=False`.
- **Google OAuth 2.0 / OpenID Connect** — Authorization Code flow with **PKCE**,
  implemented directly against Google's discovery document using `httpx` (no
  `authlib` dependency). Users are matched to existing accounts by verified
  email, then linked. Enable by setting `GOOGLE_CLIENT_ID` and
  `GOOGLE_CLIENT_SECRET`; leave blank to hide the Google button.

### Sessions and cookies

- On sign-in the server mints an opaque token (`secrets.token_urlsafe`); only its
  SHA-256 digest is stored in the `sessions` table, so a database leak cannot be
  replayed. Sessions expire after `SESSION_TTL_SECONDS` (default 7 days).
- The token lives in an **HttpOnly** cookie (`aqg_session`). A second readable
  cookie (`aqg_csrf`) carries a double-submit CSRF token that the client echoes
  back in the `X-CSRF-Token` header on every `POST`/`PUT`/`PATCH`/`DELETE`.
  Mismatches return `403 csrf_failed`.
- Set `SESSION_COOKIE_SECURE=True` on any HTTPS deployment, and a strong
  `AUTH_SECRET_KEY` (when blank a per-process value is derived, which is only
  safe for local development).

### Per-user ownership

Every assessment, document, study material and attempt is stamped with the
owning `user_id`. Reads, writes and deletes are filtered by the signed-in user,
and rows created before accounts existed (a `NULL` owner) remain visible so
existing data is never orphaned. Tests run against an override
(`tests/conftest.py`) so the original feature suite keeps passing; tests marked
`real_auth` drive the genuine cookie/session/CSRF flow.

## Requirements

- Python 3.11+
- An OpenAI-compatible API key (OpenAI, or a gateway such as OpenRouter), or a
  local vLLM/Ollama endpoint via `LLM_PROVIDER=local`

## Local setup

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env
```

Then set your key and run:

```bash
python main.py                # or: uvicorn main:app --reload
```

The app is served at `http://localhost:8000` (the SPA at `/`, docs at `/docs`,
liveness at `/health`). The SQLite store is created automatically on boot.

`.env.example` documents every setting, including upload bounds, RAG parameters,
AI provider options and rate limits. Nothing is required to boot; generation needs
a real provider key.

## API

Errors always use the envelope `{"error": "...", "detail": "..."}` with a
user-safe message; internals stay in the server log.

Every endpoint requires an authenticated session **except** `/health`,
`/api/status`, `/api/limits` and `/api/auth/providers`. State-changing requests
additionally require the CSRF header described below.

| Method | Path                              | Notes                                                     |
|--------|-----------------------------------|-----------------------------------------------------------|
| `GET`  | `/health`                         | Liveness probe, never touches the database                |
| `GET`  | `/api/status`                     | App identity, service states, aggregate counts            |
| `GET`  | `/api/dashboard`                  | Statistics, recent activity/attempts, quick actions        |
| `GET`  | `/api/limits`                     | Upload and generation bounds for the client                |
| `GET`  | `/api/auth/providers`             | Public: which sign-in methods are enabled                  |
| `GET`  | `/api/auth/me`                    | Current user (`401` when signed out)                       |
| `POST` | `/api/auth/register`              | Create an email + password account                         |
| `POST` | `/api/auth/login`                 | Sign in with email + password                              |
| `POST` | `/api/auth/logout`                | End the current session                                    |
| `POST` | `/api/auth/logout-all`            | End every other session for the account                    |
| `PATCH`| `/api/auth/profile`               | Update display name / picture                              |
| `GET`  | `/api/auth/google/start`          | Begin Google OAuth; returns the authorization URL          |
| `GET`  | `/api/auth/google/callback`       | OAuth redirect target; sets cookies, returns to the SPA    |
| `POST` | `/api/generate-quiz`              | Generate an assessment from an upload                     |
| `POST` | `/api/v1/generate`                | Legacy alias of the above                                 |
| `GET`  | `/api/quiz/{quiz_id}`             | Learner-safe assessment payload                           |
| `GET`  | `/api/quiz/{quiz_id}/answer-key`  | Requires `attempt_id`; `403` until submitted              |
| `POST` | `/api/assessment/{quiz_id}/submit`| Grade a submission and record the attempt                 |
| `GET`  | `/api/assessment/history`         | Completed attempts, newest first                          |
| `GET`  | `/api/assessment/attempts/{id}`   | One graded attempt with per-question review               |
| `GET`  | `/api/performance`                | Aggregated statistics and topic performance               |
| `POST` | `/api/generate-study-material`    | Generate summaries, flashcards, definitions, notes        |
| `GET`  | `/api/study-materials`            | List stored study resources                               |
| `GET`  | `/api/documents`                  | Processed uploads                                         |
| `GET`  | `/api/quizzes`                    | History browser: `search`, `topic`, `type`, paging        |
| `GET`  | `/api/v1/quizzes`                 | Legacy history listing                                    |
| `GET`  | `/api/v1/quizzes/{id}/source`     | Original upload metadata                                  |
| `DELETE`| `/api/v1/quizzes/{id}`            | Delete a history record                                   |

Interactive documentation is generated at `/docs`.

### Generation parameters

`POST /api/generate-quiz` (multipart):

| Field          | Type   | Default          | Notes                                        |
|----------------|--------|------------------|----------------------------------------------|
| `file`         | file   | —                | `.pdf` or `.txt`, within `MAX_UPLOAD_SIZE`   |
| `type`         | string | `multiple-choice`| Any supported format, or `mixed`             |
| `count`        | int    | `5`              | `MIN_QUESTIONS`–`MAX_QUESTIONS`              |
| `difficulty`   | string | `medium`         | `easy`, `medium`, `hard`                     |
| `topic`        | string | `""`             | Retrieval steering; falls back to a default  |
| `instructions` | string | `""`             | Extra guidance for the generator             |

Responses: `200` payload, `400` invalid input, `413` oversize upload,
`422` validation, `502` upstream AI failure.

## Persistence

`services/database.py` wraps the standard `sqlite3` driver:

- **Automatic initialization** — the file and all tables are created on startup
  through the FastAPI lifespan handler, using `CREATE TABLE IF NOT EXISTS` plus a
  `PRAGMA table_info` check, so booting repeatedly is safe.
- **Async-safe** — `sqlite3` is blocking, so every `async_*` helper dispatches to a
  worker thread. The blocking LLM call is offloaded the same way.
- **Serialized payloads** — nested results are stored as JSON text and rehydrated on
  read. Legacy rows from earlier releases are repaired on load (missing types,
  legacy key names, string ids) instead of failing.
- **Concurrency** — per-operation connections, WAL journaling and a 30s busy timeout
  allow concurrent readers and multiple uvicorn workers.
- **Working-directory independent** — the database file and the `static/` mount are
  both anchored to the project root.

Tables: `generated_quizzes`, `documents`, `study_materials`, `assessment_attempts`,
`recent_activity`, plus the authentication tables `users`, `sessions` and
`oauth_states`, and supporting indexes. Ownership is tracked through a `user_id`
column added to the content tables by a non-destructive migration; rows with a
`NULL` owner predate accounts and stay visible to everyone. The original
`generated_quizzes` schema (`id`, `topic`, `quiz_type`, `num_questions`,
`quiz_data`, `source_filename`, `created_at`, `difficulty`, `document_id`) is
preserved.

## Project layout

```
api/            routers (incl. auth), dependency wiring, auth security helpers
config/         environment-driven settings
models/         Pydantic schemas (question, quiz, assessment, study, document, user)
services/       parsing, retrieval, generation, grading, persistence, auth
static/         the SPA: index.html, css/, js/ (core modules + pages)
tests/          pytest suite
main.py         app assembly, middleware, static hosting
```

## Testing

```bash
python -m pytest tests -v
```

`tests/conftest.py` redirects the database to a throwaway file for the session, so
the suite never writes to your working `quizzes.db`.

## Deployment

The split deployment keeps the SPA and the API on separate hosts while the
browser still sees a single origin, so HttpOnly session cookies work without
cross-site plumbing.

### 1. Backend (Render)

`render.yaml` at the repository root is a Render Blueprint that builds the
FastAPI service from `aqg-system/`.

1. Push to GitHub, then in Render choose **New + → Blueprint** and select the
   repository. Render reads `render.yaml`, creates the service and prompts for
   the secrets marked `sync: false`.
2. Provide the secrets Render prompts for:
   - `AUTH_SECRET_KEY` — pre-generated by Render (`generateValue: true`).
   - `FRONTEND_URL` — the Vercel URL you create below (e.g. `https://aqg.vercel.app`).
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_REDIRECT_URI`, e.g.
     `https://<your-service>.onrender.com/api/auth/google/callback`
   - `OPENAI_API_KEY` (and `LLM_BASE_URL` if using a gateway)
   - `SESSION_COOKIE_SECURE=true`
3. The `/api/status` endpoint is the health check.

### Frontend on Vercel

1. Import the same repository into Vercel. `vercel.json` at the repo root sets
   `outputDirectory` to `aqg-system/static` and proxies `/api/*` to the backend.
2. Edit the `rewrites.destination` in `vercel.json` to your Render URL, e.g.
   `https://aqg-api.onrender.com/api/:path*`, then redeploy. Because the API is
   proxied same-origin, the session cookie is sent automatically and no CORS
   configuration is needed.
3. Set `FRONTEND_URL` on Render to the Vercel domain and redeploy the backend.

### Google Cloud Console

Create an OAuth 2.0 **Web application** client and add both redirect URIs:

```
https://<render-service>.onrender.com/api/auth/google/callback
http://localhost:8000/api/auth/google/callback
```

### Notes

- The free Render tier has an ephemeral filesystem, so SQLite is reset on each
  deploy. Attach a persistent disk and set `DATABASE_PATH` onto it, or migrate to
  a managed Postgres (a future change; the persistence layer is isolated in
  `services/database.py`).
- Never commit `.env`; `.gitignore` excludes it and `quizzes.db`. Set secrets
  through the host's environment settings.

## Docker

```bash
docker compose up --build -d     # start
docker compose logs -f           # follow logs
docker compose down              # tear down
```

The image runs a non-root `appuser`, defaults to `DEBUG=False` and serves with two
uvicorn workers. Compose bind-mounts the project into `/app`, so `quizzes.db` is
written to the host directory and survives rebuilds — on Linux, make sure the
directory is writable by uid 1000 (`chown -R 1000:1000 .`) or point `DATABASE_PATH`
at a mounted writable path. WAL journaling keeps the workers consistent against the
same file.