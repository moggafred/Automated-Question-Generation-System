"""Quiz history browsing and deletion endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Path, Query

from errors import QuizNotFoundError
from models.question import QUESTION_TYPE_LABELS
from models.quiz import Assessment
from services.database import (
    MAX_HISTORY_PAGE_SIZE,
    async_count_assessment_attempts,
    async_count_quizzes,
    async_delete_quiz,
    async_distinct_topics,
    async_list_assessment_attempts,
    async_list_quizzes,
)

router = APIRouter(prefix="/api", tags=["history"])

QUIZ_ID_DESCRIPTION = Path(..., min_length=1, description="The UUID4 tracking ID of the assessment.")


@router.get("/v1/quizzes", summary="List saved assessments")
async def list_historical_quizzes(
    limit: int = Query(20, ge=1, le=200, description="Maximum number of history records to return."),
    offset: int = Query(0, ge=0, description="Pagination offset for history browsing."),
    topic: str = Query("", description="Optional exact topic filter."),
    type: str = Query("", description="Optional question type filter."),
) -> dict:
    """Lists historically generated assessments, newest first."""
    records = await async_list_quizzes(limit=limit, offset=offset, topic=topic, quiz_type=type)
    total = await async_count_quizzes(topic=topic, quiz_type=type)

    return {
        "total": total,
        "count": len(records),
        "limit": limit,
        "offset": offset,
        "quizzes": [
            {**record, "quiz_type_label": QUESTION_TYPE_LABELS.get(record["quiz_type"], record["quiz_type"])}
            for record in records
        ],
    }


@router.get("/v1/quizzes/{quiz_id}/source", summary="Retrieve original upload metadata")
async def get_historical_quiz_source(quiz_id: str = QUIZ_ID_DESCRIPTION) -> dict:
    """Returns the original upload metadata for a historical assessment."""
    from services.database import async_get_quiz_by_id

    record = await async_get_quiz_by_id(quiz_id)
    if record is None:
        raise QuizNotFoundError()

    return {
        "quiz_id": record["quiz_id"],
        "topic": record["topic"],
        "quiz_type": record["quiz_type"],
        "num_questions": record["num_questions"],
        "source_filename": record["source_filename"],
        "created_at": record["created_at"],
    }


@router.delete("/v1/quizzes/{quiz_id}", summary="Delete an assessment from history")
async def remove_historical_quiz(quiz_id: str = QUIZ_ID_DESCRIPTION) -> dict:
    """Deletes a historical assessment record and its dependent attempts."""
    deleted = await async_delete_quiz(quiz_id)
    if not deleted:
        raise QuizNotFoundError()
    return {"quiz_id": quiz_id, "deleted": True}


@router.get("/quizzes", summary="Quiz history browser payload")
async def quiz_history(
    limit: int = Query(20, ge=1, le=200, description="Maximum number of records to return."),
    offset: int = Query(0, ge=0, description="Pagination offset."),
    topic: str = Query("", description="Optional exact topic filter."),
    type: str = Query("", description="Optional question type filter."),
    search: str = Query("", max_length=200, description="Free-text search over topic, title and filename."),
) -> dict:
    """Returns history rows enriched with attempt counts for the history page.

    A small page size is fetched and filtered in memory because the search spans
    three columns; the stored records are already capped by ``MAX_HISTORY_PAGE_SIZE``.
    """
    normalized_topic = (topic or "").strip()
    normalized_type = (type or "").strip()
    term = (search or "").strip().lower()

    records = await async_list_quizzes(
        limit=MAX_HISTORY_PAGE_SIZE,
        offset=0,
        topic=normalized_topic,
        quiz_type=normalized_type,
    )
    total = await async_count_quizzes(topic=normalized_topic, quiz_type=normalized_type)
    topics = await async_distinct_topics()

    enriched: list[dict] = []
    for record in records:
        attempts = await async_count_assessment_attempts(quiz_id=record["quiz_id"])
        recent = await async_list_assessment_attempts(limit=1, quiz_id=record["quiz_id"])
        if term:
            haystack = " ".join(
                str(record.get(key) or "") for key in ("topic", "quiz_title", "source_filename", "quiz_type")
            ).lower()
            if term not in haystack:
                continue

        enriched.append(
            {
                **record,
                "quiz_type_label": QUESTION_TYPE_LABELS.get(record["quiz_type"], record["quiz_type"]),
                "attempt_count": attempts,
                "best_percentage": max((item["percentage"] for item in recent), default=None),
            }
        )

    page = enriched[offset : offset + limit]
    return {
        "total": total,
        "count": len(page),
        "filtered": len(enriched),
        "limit": limit,
        "offset": offset,
        "topics": topics,
        "quizzes": page,
    }