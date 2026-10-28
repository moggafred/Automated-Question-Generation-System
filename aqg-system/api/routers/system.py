"""System endpoints: health, platform status and question-type metadata."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from api.security import get_optional_user, require_user
from config.settings import settings
from errors import DatabaseError
from models.question import DIFFICULTY_LABELS, QUESTION_TYPE_LABELS, QuestionType
from models.study import STUDY_MATERIAL_LABELS
from models.user import AuthenticatedUser
from services.database import (
    async_get_platform_statistics,
    async_get_recent_activity,
    async_get_recent_attempts,
)
from services.generation import MIXED_TYPE

logger = logging.getLogger("aqg.api.system")

router = APIRouter(tags=["system"])


async def _service_state(user_id: str | None = None) -> tuple[dict, bool, bool]:
    try:
        statistics = await async_get_platform_statistics(user_id=user_id)
        database_ok = True
    except Exception as exc:  # noqa: BLE001 - report readiness without leaking internals
        statistics = {}
        database_ok = False
        logger.warning("Status check could not read the database: %s", exc)

    ephemeral_storage = os.getenv("VERCEL") == "1"
    return statistics, database_ok, ephemeral_storage


def _readiness(database_ok: bool, ephemeral_storage: bool) -> dict:
    checks = {
        "database": "online" if database_ok else "degraded",
        "generation": "configured" if settings.llm_configured else "not_configured",
        "persistence": "ephemeral" if ephemeral_storage else "local_file",
    }
    warnings = []
    if not database_ok:
        warnings.append("The database is unavailable; saved data cannot be read or written.")
    if not settings.llm_configured:
        warnings.append("AI generation is unavailable until an LLM provider is configured.")
    if ephemeral_storage:
        warnings.append(
            "SQLite on Vercel Functions is temporary; saved data is not guaranteed to persist between invocations."
        )

    ready = database_ok and settings.llm_configured and not ephemeral_storage
    return {
        "status": "ready" if ready else "degraded",
        "checks": checks,
        "warnings": warnings,
    }


@router.get("/health", summary="Liveness probe")
async def health_check() -> dict:
    """Reports service liveness. Never touches the database, so it stays cheap."""
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe")
async def readiness_check():
    """Reports whether persistent storage and AI generation are ready."""
    _, database_ok, ephemeral_storage = await _service_state()
    report = _readiness(database_ok, ephemeral_storage)
    return JSONResponse(status_code=200 if report["status"] == "ready" else 503, content=report)


@router.get("/api/status", summary="API and service status")
async def platform_status(
    user: AuthenticatedUser | None = Depends(get_optional_user),
) -> dict:
    """Reports configuration state for the sidebar status panel.

    Only booleans and safe values are returned; secrets are never echoed. When a
    caller is signed in, the embedded statistics are scoped to their own data.
    """
    statistics, database_ok, ephemeral_storage = await _service_state(user.id if user else None)
    readiness = _readiness(database_ok, ephemeral_storage)

    return {
        "status": "ok",
        "readiness": readiness,
        "app_name": settings.APP_NAME,
        "app_tagline": settings.APP_TAGLINE,
        "version": settings.APP_VERSION,
        "environment": "debug" if settings.DEBUG else "production",
        "services": {
            "database": {
                "status": "online" if database_ok else "degraded",
                "path": settings.DATABASE_PATH,
                "persistence": "ephemeral" if ephemeral_storage else "local_file",
            },
            "llm": {
                "status": "configured" if settings.llm_configured else "using placeholder credentials",
                "provider": settings.LLM_PROVIDER,
                "model": settings.LOCAL_LLM_MODEL if settings.LLM_PROVIDER == "local" else settings.LLM_MODEL,
            },
            "retrieval": {
                "status": "online",
                "top_k": settings.RAG_TOP_K,
                "embedding_dim": settings.RAG_EMBED_DIM,
            },
        },
        "limits": {
            "max_upload_bytes": settings.MAX_UPLOAD_SIZE,
            "max_upload_mb": settings.max_upload_size_mb,
            "allowed_extensions": list(settings.allowed_extensions),
            "min_questions": settings.MIN_QUESTIONS,
            "max_questions": settings.MAX_QUESTIONS,
        },
        "question_types": [
            {"value": item.value, "label": QUESTION_TYPE_LABELS[item.value]} for item in QuestionType
        ]
        + [{"value": MIXED_TYPE, "label": "Mixed"}],
        "difficulty_levels": [{"value": key, "label": label} for key, label in DIFFICULTY_LABELS.items()],
        "study_material_types": [
            {"value": key, "label": label} for key, label in STUDY_MATERIAL_LABELS.items()
        ],
        "statistics": statistics,
        "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@router.get("/api/dashboard", summary="Dashboard statistics, activity and quick actions")
async def dashboard(user: AuthenticatedUser = Depends(require_user)) -> dict:
    """Aggregates everything the dashboard needs in one round trip."""
    try:
        statistics = await async_get_platform_statistics(user_id=user.id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Dashboard statistics unavailable: %s", exc)
        raise DatabaseError() from exc

    activity = await async_get_recent_activity(limit=8, user_id=user.id)
    recent_attempts = await async_get_recent_attempts(limit=5, user_id=user.id)

    return {
        "statistics": statistics,
        "recent_activity": activity,
        "recent_attempts": recent_attempts,
        "quick_actions": [
            {
                "id": "generate-quiz",
                "label": "Generate Quiz",
                "description": "Build a graded quiz from a document",
                "href": "#/generate",
                "icon": "quiz",
            },
            {
                "id": "generate-scenario",
                "label": "Create Scenario Questions",
                "description": "Test applied knowledge with realistic situations",
                "href": "#/generate?type=scenario",
                "icon": "scenario",
            },
            {
                "id": "generate-summary",
                "label": "Generate Summary",
                "description": "Condense a document into key points",
                "href": "#/study?type=summary",
                "icon": "summary",
            },
            {
                "id": "generate-flashcards",
                "label": "Generate Flashcards",
                "description": "Build revision cards for active recall",
                "href": "#/study?type=flashcards",
                "icon": "cards",
            },
        ],
    }