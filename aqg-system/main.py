"""AQG — AI-Powered Educational Assessment and Study Platform.

Application entry point. This module owns only cross-cutting concerns:

* building the FastAPI application and its lifespan (database initialisation)
* installing the rate-limit and error-translation middleware
* registering the API routers
* serving the single-page frontend from ``static/``

All request handling lives in ``api/routers``, business logic in ``services/``,
schemas in ``models/`` and configuration in ``config/``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path as FilePath

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.deps import install_exception_handlers
from api.router import register_routers
from config.settings import settings
from services.database import async_init_db
from services.rate_limit import get_limiter

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("aqg")

PROJECT_ROOT = FilePath(__file__).resolve().parent
STATIC_DIR = PROJECT_ROOT / "static"

#: Paths excluded from rate limiting so static assets and probes stay cheap.
#: A page load pulls in the shell plus ~20 modules, which must not eat the API budget.
RATE_LIMIT_EXEMPT_PREFIXES = (
    "/health",
    "/api/status",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/static",
    "/assets",
    "/css",
    "/js",
    "/favicon",
    "/logo",
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialises persistence on boot and logs a clean shutdown."""
    try:
        await async_init_db()
        logger.info("Persistence layer online at %s", settings.DATABASE_PATH)
    except Exception as exc:  # noqa: BLE001 - the API must still boot to report status
        logger.error("Database initialisation failed: %s", exc)
    yield
    logger.info("AQG shutting down")


app = FastAPI(
    title=f"{settings.APP_NAME} — {settings.APP_TAGLINE}",
    version=settings.APP_VERSION,
    description=settings.APP_DESCRIPTION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# Cross-origin support for split deployments (e.g. SPA on Vercel, API on Render).
# Credentials are enabled so the session cookie travels with the request; this
# requires an explicit origin list (a wildcard is rejected by browsers).
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Applies a sliding-window rate limit keyed by client address."""
    if not settings.RATE_LIMIT_ENABLED or request.method == "OPTIONS":
        return await call_next(request)

    if any(request.url.path.startswith(prefix) for prefix in RATE_LIMIT_EXEMPT_PREFIXES):
        return await call_next(request)

    client = request.client.host if request.client else "unknown"
    allowed, remaining, retry_after = get_limiter().allow(client)

    if not allowed:
        logger.warning("Rate limit hit for %s on %s", client, request.url.path)
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limited",
                "detail": f"Too many requests. Please wait {retry_after} seconds and try again.",
            },
            headers={"Retry-After": str(retry_after)},
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_REQUESTS)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Adds conservative security headers to every response."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


install_exception_handlers(app)
register_routers(app)

# The SPA is mounted last so it never shadows the API routes above.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=settings.DEBUG)
