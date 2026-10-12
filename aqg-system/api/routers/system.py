"""System endpoints: health, platform status and question-type metadata."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter

from api.deps import logger
from config.settings import settings
from errors import DatabaseError
from models.question import DIFFICULTY_LABELS, QUESTION_TYPE_LABELS, QuestionType
from models.study import STUDY_MATERIAL_LABELS
from services.database import (
    async_get_platform_statistics,
    async_get_recent_activity,
    async_get_recent_attempts,
)
from services.generation import MIXED_TYPE

logger = logging.getLogger("aqg.api.system")

router = APIRouter(tags=["system"])


@router.get("/health", summary="Liveness probe")
async def health_check() -> dict:
    """Reports service liveness. Never touches the database, so it stays cheap."""
    return {"status": "ok"}


@router.get("/api/status", summary="API and service status")
async def platform_status() -> dict:
    """Reports configuration state for the sidebar status panel.

    Only booleans and safe values are returned; secrets are never echoed.
    """
    try:
        statistics = await async_get_platform_statistics()
        database_ok = True
    except Exception as exc:  # noqa: BLE001 - surfaced as a degraded flag, not a 500
        statistics = {}
        database_ok = False
        logger.warning("Status check could not read the database: %s", exc)

    return {
        "status": "ok",
        "app_name": settings.APP_NAME,
        "app_tagline": settings.APP_TAGLINE,
        "version": settings.APP_VERSION,
        "environment": "debug" if settings.DEBUG else "production",
        "services": {
            "database": {
                "status": "online" if database_ok else "degraded",
                "path": settings.DATABASE_PATH,
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
async def dashboard() -> dict:
    """Aggregates everything the dashboard needs in one round trip."""
    try:
        statistics = await async_get_platform_statistics()
    except Exception as exc:  # noqa: BLE001
        logger.error("Dashboard statistics unavailable: %s", exc)
        raise DatabaseError() from exc

    activity = await async_get_recent_activity(limit=8)
    recent_attempts = await async_get_recent_attempts(limit=5)

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