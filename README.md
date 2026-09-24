# Automated Question Generation (AQG) System

An AI-powered service utilizing FastAPI and LangChain to parse PDF files and compile accurate quizzes using Retrieval-Augmented Generation (RAG).

## 🛠️ Local Setup and Configuration

1. **Clone and Initialize Environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Environment Variables Configuration:**
   Copy `.env.example` to create a production `.env` file and update your credentials:
   ```bash
   cp .env.example .env
   ```
   Inside your `.env` file, populate your configurations:
   ```env
   OPENAI_API_KEY=your_real_secret_api_key_here
   PORT=8000
   DEBUG=True
   ```

3. **Running the Application Locally:**
   ```bash
   python main.py
   ```
   The service will boot up and be accessible locally at `http://localhost:8000`.

## 🧪 Testing

Run the full testing framework locally to ensure code changes match validation rules:
```bash
python -m pytest tests -v
```

## 🐳 Docker Containerization and Orchestration

Run the entire application in a clean, isolated production-ready container workspace using Docker Compose:

* **Build and Start Container:**
  ```bash
  docker-compose up --build -d
  ```
* **View Real-Time Container Logs:**
  ```bash
  docker-compose logs -f
  ```
* **Tear Down Container Resources:**
  ```bash
  docker-compose down
  ```
