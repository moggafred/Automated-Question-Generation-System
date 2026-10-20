"""Runtime configuration for the AQG educational assessment platform.

Every value is environment driven so the same image can be deployed locally, in
Docker, or against a self-hosted LLM gateway without code changes. Defaults are
chosen so a fresh checkout boots with zero configuration (development mode).
"""

import os
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "1", "t", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class Settings(BaseSettings):
    """Typed application settings resolved from the environment and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Identity -------------------------------------------------------
    APP_NAME: str = "AQG"
    APP_TAGLINE: str = "Automated Question Generation"
    APP_VERSION: str = "2.0.0"
    APP_DESCRIPTION: str = (
        "AI-Powered Educational Assessment and Study Platform. Turns uploaded learning "
        "materials into grounded assessments, study resources and performance insight."
    )

    # --- Runtime --------------------------------------------------------
    # DEBUG defaults to False for production safety.
    DEBUG: bool = _env_bool("DEBUG", False)
    PORT: int = _env_int("PORT", 8000)

    # --- Upload constraints --------------------------------------------
    # 10MB default maximum upload limit (10 * 1024 * 1024 bytes).
    MAX_UPLOAD_SIZE: int = _env_int("MAX_UPLOAD_SIZE", 10 * 1024 * 1024)
    ALLOWED_UPLOAD_EXTENSIONS: str = os.getenv("ALLOWED_UPLOAD_EXTENSIONS", ".pdf,.txt")
    MIN_DOCUMENT_WORDS: int = _env_int("MIN_DOCUMENT_WORDS", 5)

    # --- Persistence layer ---------------------------------------------
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "quizzes.db")

    # --- Generation bounds ---------------------------------------------
    MIN_QUESTIONS: int = _env_int("MIN_QUESTIONS", 1)
    MAX_QUESTIONS: int = _env_int("MAX_QUESTIONS", 20)
    DEFAULT_QUESTIONS: int = _env_int("DEFAULT_QUESTIONS", 5)
    MAX_TOPIC_LENGTH: int = _env_int("MAX_TOPIC_LENGTH", 200)
    MAX_INSTRUCTIONS_LENGTH: int = _env_int("MAX_INSTRUCTIONS_LENGTH", 1500)

    # --- LLM providers --------------------------------------------------
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "mock_key")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    LLM_REQUEST_TIMEOUT: int = _env_int("LLM_REQUEST_TIMEOUT", 120)
    LLM_MAX_RETRIES: int = _env_int("LLM_MAX_RETRIES", 2)
    # Optional OpenAI-compatible gateway (e.g. OpenRouter) endpoint for the "openai" provider.
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "")
    LOCAL_LLM_BASE_URL: str = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:8000/v1")
    LOCAL_LLM_MODEL: str = os.getenv("LOCAL_LLM_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")

    # --- Retrieval-Augmented Generation ---------------------------------
    RAG_TOP_K: int = _env_int("RAG_TOP_K", 5)
    RAG_EMBED_DIM: int = _env_int("RAG_EMBED_DIM", 512)
    RAG_CHUNK_SIZE: int = _env_int("RAG_CHUNK_SIZE", 220)
    RAG_CHUNK_OVERLAP: int = _env_int("RAG_CHUNK_OVERLAP", 40)
    RAG_MAX_CONTEXT_CHARS: int = _env_int("RAG_MAX_CONTEXT_CHARS", 12000)

    # --- Study materials -------------------------------------------------
    MAX_FLASHCARDS: int = _env_int("MAX_FLASHCARDS", 20)
    MAX_KEY_CONCEPTS: int = _env_int("MAX_KEY_CONCEPTS", 12)

    # --- Security / rate limiting ---------------------------------------
    RATE_LIMIT_ENABLED: bool = _env_bool("RATE_LIMIT_ENABLED", True)
    RATE_LIMIT_REQUESTS: int = _env_int("RATE_LIMIT_REQUESTS", 240)
    RATE_LIMIT_WINDOW_SECONDS: int = _env_int("RATE_LIMIT_WINDOW_SECONDS", 60)

    # --- Authentication / sessions --------------------------------------
    # Signing material for opaque session identifiers. A random value is derived
    # per process when unset (fine for local development, never for production).
    AUTH_SECRET_KEY: str = os.getenv("AUTH_SECRET_KEY", "")
    # Secret for the signed session cookie used by authlib's OAuth state storage.
    SESSION_SECRET: str = os.getenv("SESSION_SECRET", "")
    SESSION_COOKIE_NAME: str = os.getenv("SESSION_COOKIE_NAME", "aqg_session")
    CSRF_COOKIE_NAME: str = os.getenv("CSRF_COOKIE_NAME", "aqg_csrf")
    # Seven days by default.
    SESSION_TTL_SECONDS: int = _env_int("SESSION_TTL_SECONDS", 60 * 60 * 24 * 7)
    SESSION_COOKIE_SECURE: bool = _env_bool("SESSION_COOKIE_SECURE", False)
    SESSION_COOKIE_SAMESITE: str = os.getenv("SESSION_COOKIE_SAMESITE", "lax")
    # Ten minutes for an in-flight OAuth handshake.
    OAUTH_STATE_TTL_SECONDS: int = _env_int("OAUTH_STATE_TTL_SECONDS", 600)

    # --- Email + password accounts --------------------------------------
    EMAIL_PASSWORD_ENABLED: bool = _env_bool("EMAIL_PASSWORD_ENABLED", True)
    PASSWORD_MIN_LENGTH: int = _env_int("PASSWORD_MIN_LENGTH", 8)
    PASSWORD_MAX_LENGTH: int = _env_int("PASSWORD_MAX_LENGTH", 128)

    # --- Google OAuth 2.0 / OpenID Connect ------------------------------
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    # When blank the redirect URI is derived from the incoming request URL.
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "")
    GOOGLE_DISCOVERY_URL: str = os.getenv(
        "GOOGLE_DISCOVERY_URL",
        "https://accounts.google.com/.well-known/openid-configuration",
    )

    # --- Deployment / cross-origin --------------------------------------
    # Where users are sent after a successful OAuth round trip. Blank means the
    # request origin (single-origin deployment).
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "")
    # Comma-separated list of browser origins allowed to call the API directly.
    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "")
    # Set when the app runs behind a TLS-terminating proxy (Vercel/Render).
    TRUST_PROXY_HEADERS: bool = _env_bool("TRUST_PROXY_HEADERS", True)

    @property
    def allowed_extensions(self) -> tuple[str, ...]:
        """Lower-cased, dot-prefixed extension whitelist used by upload validation."""
        parsed = tuple(
            f".{part.strip().lstrip('.').lower()}"
            for part in self.ALLOWED_UPLOAD_EXTENSIONS.split(",")
            if part.strip()
        )
        return parsed or (".pdf", ".txt")

    @property
    def max_upload_size_mb(self) -> int:
        return max(1, self.MAX_UPLOAD_SIZE // (1024 * 1024))

    @property
    def llm_configured(self) -> bool:
        """True when a real provider credential is present (never echoes the key)."""
        if self.LLM_PROVIDER == "local":
            return bool(self.LOCAL_LLM_BASE_URL)
        return bool(self.OPENAI_API_KEY) and self.OPENAI_API_KEY not in ("mock_key", "your_openai_api_key_here")

    @property
    def google_oauth_enabled(self) -> bool:
        """True when Google OAuth credentials are configured (never echoes them)."""
        return bool(self.GOOGLE_CLIENT_ID) and bool(self.GOOGLE_CLIENT_SECRET)

    @property
    def auth_configured(self) -> bool:
        """True when at least one sign-in method is available."""
        return self.google_oauth_enabled or self.EMAIL_PASSWORD_ENABLED

    @property
    def cors_origins(self) -> tuple[str, ...]:
        """Normalised list of browser origins permitted to call the API directly."""
        origins = [part.strip().rstrip("/") for part in self.ALLOWED_ORIGINS.split(",") if part.strip()]
        if not origins and self.FRONTEND_URL.strip():
            origins.append(self.FRONTEND_URL.strip().rstrip("/"))
        return tuple(dict.fromkeys(origins))

    @property
    def auth_secret_is_default(self) -> bool:
        """True when no explicit signing key was supplied."""
        return not self.AUTH_SECRET_KEY.strip()


settings = Settings()

ProviderName = Literal["openai", "local"]