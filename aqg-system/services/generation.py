"""Generation orchestration: retrieve -> generate -> validate -> persist.

This is the business-logic layer the API routes call. It owns the UUID4 tracking
lifecycle, grounding references and the guarantee that a learner-facing payload
never contains an answer key before submission.
"""

from __future__ import annotations

import logging
import uuid

from config.settings import settings
from errors import (
    GenerationError,
    InvalidQuestionCountError,
    InvalidQuestionTypeError,
    ValidationError,
)
from models.question import Difficulty, QuestionType, resolve_difficulty, resolve_question_type
from models.quiz import Assessment, group_case_studies
from services.documents import IndexedDocument, grounding_reference, run_blocking
from services.evaluator import QuizEvaluationAgent
from services.generator import QuestionGeneratorService, default_retrieval_query
from services.retriever import RetrievedChunk

logger = logging.getLogger("aqg.generation")

#: Pseudo type accepted by the UI/API meaning "let the AI pick a sensible spread".
MIXED_TYPE = "mixed"


def resolve_question_count(raw: int | str | None) -> int:
    """Validates a requested question count against the configured bounds."""
    try:
        count = int(raw if raw is not None else settings.DEFAULT_QUESTIONS)
    except (TypeError, ValueError):
        raise InvalidQuestionCountError("Please enter a whole number of questions.") from None

    if count < settings.MIN_QUESTIONS or count > settings.MAX_QUESTIONS:
        raise InvalidQuestionCountError(
            f"Please choose between {settings.MIN_QUESTIONS} and {settings.MAX_QUESTIONS} questions."
        )
    return count


def resolve_generation_type(raw: str | None) -> str:
    """Validates the requested question type, allowing the ``mixed`` pseudo type."""
    candidate = (raw or "").strip().lower()
    if candidate in ("", MIXED_TYPE):
        return MIXED_TYPE
    resolved = resolve_question_type(candidate)
    if resolved is None:
        supported = ", ".join(item.value for item in QuestionType) + f", {MIXED_TYPE}"
        raise InvalidQuestionTypeError(f"That question type is not supported. Choose one of: {supported}.")
    return resolved.value


def resolve_topic(raw: str | None) -> str:
    """Normalises and bounds the optional retrieval steering topic."""
    topic = (raw or "").strip()
    if len(topic) > settings.MAX_TOPIC_LENGTH:
        raise ValidationError(
            f"Please keep the topic under {settings.MAX_TOPIC_LENGTH} characters."
        )
    return topic


def resolve_instructions(raw: str | None) -> str:
    """Normalises and bounds the optional custom instructions."""
    instructions = (raw or "").strip()
    if len(instructions) > settings.MAX_INSTRUCTIONS_LENGTH:
        raise ValidationError(
            f"Please keep custom instructions under {settings.MAX_INSTRUCTIONS_LENGTH} characters."
        )
    return instructions


async def generate_assessment(
    *,
    indexed: IndexedDocument,
    question_type: str,
    count: int,
    difficulty: Difficulty | str = Difficulty.MEDIUM,
    topic: str = "",
    custom_instructions: str = "",
    generator: QuestionGeneratorService | None = None,
) -> tuple[Assessment, list[RetrievedChunk]]:
    """Runs retrieval and AI generation, then validates the result.

    Returns the validated assessment and the context chunks it was grounded in.
    """
    engine = generator or QuestionGeneratorService()
    resolved_type = resolve_generation_type(question_type)
    resolved_count = resolve_question_count(count)
    resolved_topic = resolve_topic(topic)
    resolved_instructions = resolve_instructions(custom_instructions)
    resolved_difficulty = (
        difficulty if isinstance(difficulty, Difficulty) else resolve_difficulty(str(difficulty))
    )

    query = default_retrieval_query(resolved_topic)
    context, chunks = await run_blocking(indexed.retriever.build_context, query)
    if not context:
        raise GenerationError(
            "We could not find any relevant content in that document. "
            "Please try a different topic or a longer document."
        )

    raw_payload = await run_generation(
        engine.generate_quiz,
        context,
        resolved_type,
        resolved_count,
        resolved_difficulty.value,
        resolved_topic,
        resolved_instructions,
    )

    audited = await run_blocking(QuizEvaluationAgent.audit_assessment, raw_payload)
    reference = grounding_reference(chunks)

    assessment = build_assessment(
        audited,
        topic=resolved_topic,
        question_type=resolved_type,
        difficulty=resolved_difficulty,
        source_reference=reference,
    )

    if assessment.is_empty:
        raise GenerationError(
            "The AI could not produce usable questions from this document. "
            "Try a different question type, a narrower topic, or a longer document."
        )

    logger.info(
        "Generated %s %s questions from %s",
        assessment.question_count,
        resolved_type,
        indexed.document.filename,
    )
    return assessment, chunks


async def run_generation(func, *args):
    """Executes a blocking generator call off the event loop."""
    try:
        return await run_blocking(func, *args)
    except GenerationError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalise unexpected provider failures
        logger.exception("Assessment generation failed: %s", exc)
        raise GenerationError(
            "We could not generate the assessment right now. Please try again.",
            detail=str(exc),
        ) from exc


def build_assessment(
    audited_payload: dict,
    *,
    topic: str = "",
    question_type: str = "",
    difficulty: Difficulty = Difficulty.MEDIUM,
    source_reference: str = "",
) -> Assessment:
    """Converts an audited payload into a validated :class:`Assessment`.

    Every item receives a grounding reference so learners can trace an answer
    back to the retrieved source context.
    """
    payload = dict(audited_payload)
    raw_questions = payload.get("questions") or []

    enriched: list[dict] = []
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        record = dict(item)
        if not record.get("source_reference") and source_reference:
            record["source_reference"] = source_reference
        if not record.get("topic") and topic:
            record["topic"] = topic
        enriched.append(record)

    payload["questions"] = enriched
    payload["topic"] = topic or payload.get("topic", "")
    payload["question_type"] = question_type or payload.get("question_type", "")
    payload["difficulty"] = difficulty.value if isinstance(difficulty, Difficulty) else str(difficulty)

    try:
        assessment = Assessment.from_payload(payload)
    except Exception as exc:  # noqa: BLE001 - invalid schema is a friendly 502
        logger.error("Generated assessment failed schema validation: %s", exc)
        raise GenerationError(
            "The AI returned content that could not be validated. Please try generating again.",
            detail=f"assessment validation error: {exc}",
        ) from exc

    if not assessment.question_type:
        assessment.question_type = question_type

    assessment.case_studies = group_case_studies(assessment)
    return assessment


async def persist_assessment(
    assessment: Assessment,
    *,
    topic: str,
    question_type: str,
    document: object | None = None,
    user_id: str | None = None,
) -> str:
    """Stores the assessment and returns its UUID4 tracking ID."""
    from services.database import async_save_quiz

    quiz_id = str(uuid.uuid4())
    await async_save_quiz(
        quiz_id=quiz_id,
        topic=topic,
        quiz_type=question_type,
        num_questions=assessment.question_count,
        quiz_data=assessment.to_dict(),
        source_filename=getattr(document, "filename", None),
        difficulty=str(assessment.difficulty),
        document_id=getattr(document, "id", None),
        user_id=user_id,
    )
    return quiz_id


__all__ = [
    "MIXED_TYPE",
    "build_assessment",
    "generate_assessment",
    "persist_assessment",
    "resolve_difficulty",
    "resolve_generation_type",
    "resolve_instructions",
    "resolve_question_count",
    "resolve_topic",
]