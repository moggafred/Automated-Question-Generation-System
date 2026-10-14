"""Assessment retrieval endpoints (one quiz by tracking ID)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from api.security import require_user
from errors import AttemptNotSubmittedError, QuizNotFoundError
from models.quiz import Assessment
from models.user import AuthenticatedUser
from services.database import async_get_assessment_attempt, async_get_quiz_by_id

router = APIRouter(prefix="/api", tags=["quizzes"])

QUIZ_ID_DESCRIPTION = Path(..., min_length=1, description="The UUID4 tracking ID of the assessment.")


def build_quiz_response(record: dict) -> dict:
    """Shapes a stored quiz row into the learner-facing assessment payload."""
    assessment = Assessment.from_payload(record["quiz_data"])
    payload = assessment.to_public_dict()
    payload.update(
        {
            "quiz_id": record["quiz_id"],
            "topic": record["topic"],
            "quiz_type": record["quiz_type"],
            "difficulty": record.get("difficulty", "medium"),
            "num_questions": record["num_questions"],
            "source_filename": record["source_filename"],
            "document_id": record.get("document_id"),
            "created_at": record["created_at"],
            "title": assessment.quiz_title,
        }
    )
    return payload


async def _load_quiz(quiz_id: str, user_id: str) -> dict:
    record = await async_get_quiz_by_id(quiz_id, user_id=user_id)
    if record is None:
        raise QuizNotFoundError()
    return record


@router.get("/quiz/{quiz_id}", summary="Retrieve an assessment by tracking ID")
async def get_quiz(
    quiz_id: str = QUIZ_ID_DESCRIPTION,
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    """Returns a previously generated assessment for taking or reviewing."""
    return build_quiz_response(await _load_quiz(quiz_id, user.id))


@router.get("/v1/quizzes/{quiz_id}", summary="Retrieve an assessment (legacy alias)")
async def get_quiz_legacy(
    quiz_id: str = QUIZ_ID_DESCRIPTION,
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    """Backwards-compatible alias of ``GET /api/quiz/{quiz_id}``."""
    return build_quiz_response(await _load_quiz(quiz_id, user.id))


@router.get("/quiz/{quiz_id}/answer-key", summary="Retrieve the answer key for a submitted assessment")
async def get_answer_key(
    quiz_id: str = QUIZ_ID_DESCRIPTION,
    attempt_id: str = Query(
        ...,
        min_length=1,
        description="A submitted attempt ID. The key is refused without one.",
    ),
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    """Returns the authoritative answers for review.

    The attempt ID is mandatory and must belong to this assessment, so the key
    cannot be read before the learner has actually submitted their answers.
    """
    record = await _load_quiz(quiz_id, user.id)

    attempt = await async_get_assessment_attempt(attempt_id, user_id=user.id)
    if attempt is None:
        raise AttemptNotSubmittedError()

    if attempt.get("quiz_id") != record["quiz_id"]:
        raise AttemptNotSubmittedError()

    assessment = Assessment.from_payload(record["quiz_data"])
    return {
        "quiz_id": record["quiz_id"],
        "attempt_id": attempt["attempt_id"],
        "title": assessment.quiz_title,
        "answers": [
            {
                "question_id": question.id,
                "correct_answer": question.correct_answer,
                "explanation": question.explanation,
                "marking_criteria": question.marking_criteria,
                "source_reference": question.source_reference,
            }
            for question in assessment.questions
        ],
    }