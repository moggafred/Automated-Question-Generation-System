import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    APP_NAME: str = "Automated Question Generation System"

    # 5. Gate response behavior: DEBUG defaults to False for production safety
    DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")
    PORT: int = int(os.getenv("PORT", 8000))

    # 6. Enforce a 10MB maximum upload limit (10 * 1024 * 1024 bytes)
    MAX_UPLOAD_SIZE: int = int(os.getenv("MAX_UPLOAD_SIZE", 10 * 1024 * 1024))

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "mock_key")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")
    # Optional OpenAI-compatible gateway (e.g. OpenRouter) endpoint for the "openai" provider
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "")
    LOCAL_LLM_BASE_URL: str = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:8000/v1")
    LOCAL_LLM_MODEL: str = os.getenv("LOCAL_LLM_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")
    RAG_TOP_K: int = os.getenv("RAG_TOP_K", 3)
    RAG_EMBED_DIM: int = os.getenv("RAG_EMBED_DIM", 512)

settings = Settings()