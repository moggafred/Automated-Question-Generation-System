# Automated Question Generation (AQG) System

An AI-powered service utilizing FastAPI and LangChain to parse PDF/TXT documents and compile accurate quizzes using Retrieval-Augmented Generation (RAG).

## Pipeline

```
upload (.pdf/.txt) -> DocumentParserService -> semantic chunking
  -> DocumentRetriever (FAISS hashing bag-of-words, top-K by topic query)
  -> QuestionGeneratorService (LLM, JSON-schema forced output)
  -> QuizEvaluationAgent (structure guardrail) -> HTTP response
```

## Requirements

- Python 3.11+
- An OpenAI-compatible API key (e.g. OpenAI or [OpenRouter](https://openrouter.ai) free models), or a local vLLM/Ollama endpoint (`LLM_PROVIDER=local`)

## 🛠️ Local Setup and Configuration

1. **Clone and Initialize Environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Environment Variables Configuration:**
   Copy `.env.example` to create a `.env` file and update your credentials:
   ```bash
   copy .env.example .env    # Windows
   cp .env.example .env      # Linux/macOS
   ```
   Inside your `.env`, populate your configurations:
   ```env
   OPENAI_API_KEY=your_real_secret_api_key_here
   LLM_BASE_URL=https://openrouter.ai/api/v1   # optional gateway; empty for OpenAI directly
   LLM_MODEL=google/gemma-4-26b-a4b-it:free    # e.g. gpt-4o for OpenAI
   PORT=8000
   DEBUG=False
   ```

3. **Running the Application Locally:**
   ```bash
   python main.py
   ```
   The service boots and is accessible at `http://localhost:8000`. The UI is served at the root; liveness probe at `GET /health`.

## 📡 API

`POST /api/v1/generate` (multipart form):

| Field   | Type   | Required | Notes                                    |
|---------|--------|----------|------------------------------------------|
| `file`  | file   | yes      | `.pdf` or `.txt`, max 10MB               |
| `type`  | string | no       | `multiple-choice` (default), `short-answer`, `fill-in-the-blank` |
| `count` | int    | no       | 1-10 (default 3)                         |
| `topic` | string | no       | retrieval query steering RAG             |

Responses: `200` quiz payload, `400` invalid input, `413` oversize file, `500` on LLM/upstream failure.

## 🧪 Testing

Run the full testing framework from the `aqg-system` directory:
```bash
python -m pytest tests -v
```

## 🐳 Docker Containerization and Orchestration

Run the application in a clean, isolated production-ready container using Docker Compose (requires Docker Desktop or equivalent):

* **Build and Start Container:**
  ```bash
  docker compose up --build -d
  ```
* **View Real-Time Container Logs:**
  ```bash
  docker compose logs -f
  ```
* **Tear Down Container Resources:**
  ```bash
  docker compose down
  ```

The Dockerfile runs a non-root `appuser`, is `DEBUG=False` by default, and serves with 2 uvicorn workers on `${PORT}` (default 8000).