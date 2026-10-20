"""Assessment submission, attempt history and performance endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, Path, Query

from api.security import require_user
from errors import AssessmentError, DatabaseError, QuizNotFoundError
from models.assessment import AssessmentSubmission
from models.question import QUESTION_TYPE_LABELS
from models.user import AuthenticatedUser
from services.assessment import grade_and_persist
from services.database import (
    async_count_assessment_attempts,
    async_get_assessment_attempt,
    async_get_platform_statistics,
    async_get_quiz_by_id,
    async_get_recent_attempts,
    async_get_topic_performance,
    async_list_assessment_attempts,
)
from models.quiz import Assessment

router = APIRouter(prefix="/api", tags=["assessments"])

logger = logging.getLogger("aqg.api.assessments")

QUIZ_ID_DESCRIPTION = Path(..., min_length=1, description="The UUID4 tracking ID of the assessment.")
ATTEMPT_ID_DESCRIPTION = Path(..., min_length=1, description="The UUID4 tracking ID of the attempt.")


async def _require_quiz(quiz_id: str, user_id: str) -> dict:
    record = await async_get_quiz_by_id(quiz_id, user_id=user_id)
    if record is None:
        raise QuizNotFoundError()
    return record


@router.post("/assessment/{quiz_id}/submit", summary="Submit an assessment for automatic grading")
async def submit_assessment(
    quiz_id: str = QUIZ_ID_DESCRIPTION,
    submission: AssessmentSubmission = Body(...),
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    """Grades a submission against the stored assessment and records the attempt.

    The answer key is never sent to the client beforehand, so the score is the
    only way to reveal it.
    """
    if not submission.answers:
        raise AssessmentError("Please answer at least one question before submitting.")

    record = await _require_quiz(quiz_id, user.id)
    assessment = Assessment.from_payload(record["quiz_data"])

    if not assessment.questions:
        raise AssessmentError("This assessment has no questions to grade.")

    valid_ids = {question.id for question in assessment.questions}
    unknown = [answer.question_id for answer in submission.answers if answer.question_id not in valid_ids]
    if unknown:
        raise AssessmentError("Some answers do not belong to this assessment. Please retake it.")

    try:
        result = await grade_and_persist(
            record["quiz_data"],
            submission,
            quiz_id=quiz_id,
            quiz_topic=record["topic"],
            user_id=user.id,
        )
    except DatabaseError:
        raise
    except Exception as exc:  # noqa: BLE001 - grading failure must not leak internals
        logger.exception("Grading failed for quiz %s: %s", quiz_id, exc)
        raise AssessmentError("We could not grade this submission. Please try again.") from exc

    return {"result": result.model_dump(mode="json")}


@router.get("/assessment/history", summary="List completed assessment attempts")
async def assessment_history(
    limit: int = Query(20, ge=1, le=200, description="Maximum number of attempts to return."),
    offset: int = Query(0, ge=0, description="Pagination offset."),
    quiz_id: str = Query("", description="Optional filter to a single assessment."),
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    """Returns completed attempts, newest first."""
    attempts = await async_list_assessment_attempts(
        limit=limit, offset=offset, quiz_id=quiz_id or None, user_id=user.id
    )
    total = await async_count_assessment_attempts(quiz_id=quiz_id or None, user_id=user.id)

    return {
        "total": total,
        "count": len(attempts),
        "limit": limit,
        "offset": offset,
        "attempts": attempts,
    }


@router.get("/assessment/{quiz_id}/attempts", summary="Attempts recorded for one assessment")
async def attempts_for_quiz(
    quiz_id: str = QUIZ_ID_DESCRIPTION,
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    """Returns every attempt recorded against a single assessment."""
    await _require_quiz(quiz_id, user.id)
    attempts = await async_list_assessment_attempts(limit=200, quiz_id=quiz_id, user_id=user.id)
    return {"quiz_id": quiz_id, "count": len(attempts), "attempts": attempts}


@router.get("/assessment/attempts/{attempt_id}", summary="Retrieve one graded attempt")
async def get_attempt(
    attempt_id: str = ATTEMPT_ID_DESCRIPTION,
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    """Returns the full graded result including the per-question review."""
    attempt = await async_get_assessment_attempt(attempt_id, user_id=user.id)
    if attempt is None:
        raise AssessmentError("We could not find that assessment attempt.")

    review = attempt.pop("review", [])
    answers = attempt.pop("answers", [])

    band = "excellent"
    percentage = attempt["percentage"]
    if percentage < 90:
        band = "very-good" if percentage >= 80 else "good" if percentage >= 70 else "needs-improvement"

    return {
        "attempt": attempt,
        "answers": answers,
        "review": review,
        "performance_band": band,
    }


@router.get("/performance", summary="Aggregate performance statistics")
async def performance(user: AuthenticatedUser = Depends(require_user)) -> dict:
    """Returns real aggregates from stored attempts.

    No value here is fabricated: with no attempt history every metric is zero and
    ``has_data`` is False so the UI can render an honest empty state.
    """
    try:
        statistics = await async_get_platform_statistics(user_id=user.id)
        topic_performance = await async_get_topic_performance(user_id=user.id)
        recent = await async_get_recent_attempts(limit=8, user_id=user.id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Performance aggregation failed: %s", exc)
        raise DatabaseError() from exc

    total_attempts = statistics.get("assessments_completed", 0)

    return {
        "has_data": total_attempts > 0,
        "total_assessments": total_attempts,
        "average_score": statistics.get("average_score", 0.0),
        "highest_score": statistics.get("highest_score", 0.0),
        "lowest_score": statistics.get("lowest_score", 0.0),
        "questions_answered": statistics.get("questions_answered", 0),
        "questions_generated": statistics.get("questions_generated", 0),
        "quizzes_generated": statistics.get("quizzes_generated", 0),
        "documents_processed": statistics.get("documents_processed", 0),
        "topic_performance": topic_performance,
        "recent_attempts": recent,
        "score_distribution": _distribution(topic_performance),
    }


def _distribution(topic_performance: list[dict]) -> list[dict]:
    """Buckets topics into performance bands for the performance chart."""
    bands = [
        {"band": "Excellent (90-100)", "min": 90, "topics": 0},
        {"band": "Very Good (80-89)", "min": 80, "topics": 0},
        {"band": "Good (70-79)", "min": 70, "topics": 0},
        {"band": "Below 70", "min": 0, "topics": 0},
    ]
    for entry in topic_performance:
        score = float(entry.get("average_percentage") or 0)
        for band in bands:
            if score >= band["min"]:
                band["topics"] += 1
                break
    return bands


@router.get("/assessment-types", summary="Question type vocabulary for the client")
async def assessment_types() -> dict:
    """Returns the question type labels used by review and result screens."""
    return {"types": [{"value": key, "label": label} for key, label in QUESTION_TYPE_LABELS.items()]}