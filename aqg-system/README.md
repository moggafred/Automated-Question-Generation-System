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

| Method | Path                              | Notes                                                     |
|--------|-----------------------------------|-----------------------------------------------------------|
| `GET`  | `/health`                         | Liveness probe, never touches the database                |
| `GET`  | `/api/status`                     | App identity, service states, aggregate counts            |
| `GET`  | `/api/dashboard`                  | Statistics, recent activity/attempts, quick actions        |
| `GET`  | `/api/limits`                     | Upload and generation bounds for the client                |
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
`recent_activity`, plus supporting indexes. The original `generated_quizzes` schema
(`id`, `topic`, `quiz_type`, `num_questions`, `quiz_data`, `source_filename`,
`created_at`, `difficulty`, `document_id`) is preserved.

## Project layout

```
api/            routers, dependency wiring, exception handlers
config/         environment-driven settings
models/         Pydantic schemas (question, quiz, assessment, study, document)
services/       parsing, retrieval, generation, grading, persistence
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