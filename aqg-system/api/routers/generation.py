"""Assessment generation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile

from api.deps import logger
from api.security import require_user
from config.settings import settings
from models.question import resolve_difficulty
from models.user import AuthenticatedUser
from services.documents import ingest_document
from services.generation import (
    generate_assessment,
    persist_assessment,
    resolve_question_count,
)
from services.generator import QuestionGeneratorService

router = APIRouter(prefix="/api", tags=["generation"])

#: Shared generator instance so the LLM client is constructed once per process.
generator_service = QuestionGeneratorService()


def _response_payload(assessment, *, quiz_id: str, topic: str, question_type: str, document) -> dict:
    """Builds the client-facing payload: questions only, never the answer key.

    The answer key stays server-side in SQLite and is only revealed after
    submission, which prevents a learner from reading answers off the network
    tab before completing the assessment.
    """
    metadata = {
        "quiz_id": quiz_id,
        "topic": topic,
        "quiz_type": question_type,
        "num_questions": assessment.question_count,
        "difficulty": str(assessment.difficulty),
        "source_filename": document.filename,
        "document_id": document.id,
        "title": assessment.quiz_title,
        "total_points": assessment.total_points,
    }
    payload = assessment.to_public_dict()
    payload.update(metadata)
    return payload


async def _run_generation(
    file: UploadFile,
    *,
    question_type: str,
    count: int,
    difficulty: str,
    topic: str,
    custom_instructions: str,
    user_id: str,
) -> dict:
    """Shared implementation for both generation endpoints."""
    resolved_count = resolve_question_count(count)
    resolved_difficulty = resolve_difficulty(difficulty)

    indexed = await ingest_document(file, user_id=user_id)
    assessment, _chunks = await generate_assessment(
        indexed=indexed,
        question_type=question_type,
        count=resolved_count,
        difficulty=resolved_difficulty,
        topic=topic,
        custom_instructions=custom_instructions,
        generator=generator_service,
    )

    topic_label = topic.strip()
    quiz_id = await persist_assessment(
        assessment,
        topic=topic_label,
        question_type=question_type,
        document=indexed.document,
        user_id=user_id,
    )

    return _response_payload(
        assessment,
        quiz_id=quiz_id,
        topic=topic_label,
        question_type=question_type,
        document=indexed.document,
    )


@router.post("/generate-quiz", summary="Generate a grounded assessment from an uploaded document")
async def generate_quiz(
    file: UploadFile = File(..., description="A PDF or TXT learning material."),
    type: str = Form("multiple-choice", description="Question format for the assessment."),
    count: int = Form(5, description="Number of questions to generate."),
    difficulty: str = Form("medium", description="easy, medium or hard."),
    topic: str = Form("", description="Optional topic focus for retrieval."),
    instructions: str = Form("", description="Optional custom instructions for the AI."),
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    """Ingests a document, retrieves relevant context and returns a fresh assessment."""
    logger.info(
        "Generation requested: type=%s count=%s difficulty=%s topic=%s",
        type,
        count,
        difficulty,
        topic.strip() or "(document-wide)",
    )
    return await _run_generation(
        file,
        question_type=type,
        count=count,
        difficulty=difficulty,
        topic=topic,
        custom_instructions=instructions,
        user_id=user.id,
    )


@router.post("/v1/generate", summary="Generate a grounded assessment (legacy alias)")
async def generate_quiz_legacy(
    file: UploadFile = File(..., description="A PDF or TXT learning material."),
    type: str = Form("multiple-choice", description="Question format for the assessment."),
    count: int = Form(3, description="Number of questions to generate."),
    topic: str = Form("", description="Optional topic focus for retrieval."),
    difficulty: str = Form("medium", description="easy, medium or hard."),
    instructions: str = Form("", description="Optional custom instructions for the AI."),
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    """Backwards-compatible endpoint retained from the original release.

    Same pipeline as ``POST /api/generate-quiz``; answers are withheld here too,
    and are only available after submitting the assessment.
    """
    return await _run_generation(
        file,
        question_type=type,
        count=count,
        difficulty=difficulty,
        topic=topic,
        custom_instructions=instructions,
        user_id=user.id,
    )


@router.get("/limits", summary="Upload and generation limits for the client")
async def generation_limits() -> dict:
    """Exposes the configured bounds so the UI never hardcodes them."""
    return {
        "max_upload_bytes": settings.MAX_UPLOAD_SIZE,
        "max_upload_mb": settings.max_upload_size_mb,
        "allowed_extensions": list(settings.allowed_extensions),
        "min_questions": settings.MIN_QUESTIONS,
        "max_questions": settings.MAX_QUESTIONS,
        "default_questions": settings.DEFAULT_QUESTIONS,
        "quick_counts": [5, 10, 15, 20],
    }