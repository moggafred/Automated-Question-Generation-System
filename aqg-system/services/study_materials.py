"""AI study-material generation: summaries, concepts, flashcards and revision notes.

Generation is grounded in the same retrieved context used for question
generation, so study resources can never contradict the source document. Results
are validated through :class:`~models.study.StudyMaterial` before persistence so a
malformed AI response is rejected rather than stored.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Iterable

from config.settings import settings
from errors import GenerationError, InvalidAIResponseError
from models.document import ParsedDocument
from models.question import normalize_answer_text
from models.study import STUDY_MATERIAL_LABELS, StudyMaterial, StudyMaterialType
from services.documents import IndexedDocument
from services.generator import QuestionGeneratorService, default_retrieval_query
from services.retriever import RetrievedChunk

logger = logging.getLogger("aqg.study_materials")

MIN_ITEMS = 1


def _dedupe(values: Iterable[Any]) -> list[str]:
    """Removes blank and duplicate free-text entries, preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = normalize_answer_text(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _clean_concepts(concepts: Iterable[Any], limit: int) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for concept in concepts or []:
        if not isinstance(concept, dict):
            continue
        title = str(concept.get("title") or "").strip()
        description = str(concept.get("description") or "").strip()
        key = normalize_answer_text(title)
        if not title or not description or key in seen:
            continue
        seen.add(key)
        cleaned.append(
            {
                "title": title[:160],
                "description": description[:1200],
                "why_it_matters": str(concept.get("why_it_matters") or "").strip()[:600],
            }
        )
        if len(cleaned) >= limit:
            break
    return cleaned


def _clean_definitions(definitions: Iterable[Any], limit: int) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in definitions or []:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term") or "").strip()
        definition = str(item.get("definition") or "").strip()
        key = normalize_answer_text(term)
        if not term or not definition or key in seen:
            continue
        seen.add(key)
        cleaned.append(
            {
                "term": term[:160],
                "definition": definition[:1200],
                "example": str(item.get("example") or "").strip()[:600],
            }
        )
        if len(cleaned) >= limit:
            break
    return cleaned


def _clean_flashcards(flashcards: Iterable[Any], limit: int) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in flashcards or []:
        if not isinstance(card, dict):
            continue
        front = str(card.get("front") or "").strip()
        back = str(card.get("back") or "").strip()
        key = normalize_answer_text(front)
        if not front or not back or key in seen:
            continue
        seen.add(key)
        cleaned.append(
            {
                "front": front[:600],
                "back": back[:1200],
                "hint": str(card.get("hint") or "").strip()[:300],
                "topic": str(card.get("topic") or "").strip()[:160],
            }
        )
        if len(cleaned) >= limit:
            break
    return cleaned


def _clean_revision_notes(notes: Iterable[Any], limit: int) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for note in notes or []:
        if not isinstance(note, dict):
            continue
        heading = str(note.get("heading") or "").strip()
        body = str(note.get("body") or "").strip()
        if not heading or not body:
            continue
        cleaned.append(
            {
                "heading": heading[:200],
                "body": body[:2000],
                "key_takeaway": str(note.get("key_takeaway") or "").strip()[:600],
            }
        )
        if len(cleaned) >= limit:
            break
    return cleaned


def build_title(material_type: StudyMaterialType, topic: str, filename: str) -> str:
    """Derives a human readable title for a generated study resource."""
    label = STUDY_MATERIAL_LABELS.get(material_type.value, "Study Material")
    if topic:
        return f"{label}: {topic}"
    stem = (filename or "Document").rsplit("/", 1)[-1]
    return f"{label}: {stem}"


def normalize_study_payload(
    raw: dict[str, Any],
    *,
    material_type: StudyMaterialType,
    topic: str,
    filename: str,
    document: ParsedDocument | None = None,
) -> StudyMaterial:
    """Validates and cleans a raw AI payload into a storable study resource."""
    if not isinstance(raw, dict):
        raise InvalidAIResponseError(
            "The AI returned an unexpected response. Please try generating again.",
            detail=f"study payload was {type(raw)!r}",
        )

    summary_payload = raw.get("summary")
    summary_block: dict[str, Any] | None = None
    if isinstance(summary_payload, dict):
        overview = str(summary_payload.get("overview") or "").strip()
        points = _dedupe(summary_payload.get("points") or [])
        outcomes = _dedupe(summary_payload.get("learning_outcomes") or [])
        if overview or points:
            summary_block = {
                "title": str(summary_payload.get("title") or "").strip()[:240] or build_title(material_type, topic, filename),
                "overview": overview[:4000],
                "points": points[:12],
                "learning_outcomes": outcomes[:8],
            }

    material = StudyMaterial.from_content(
        material_type=material_type.value,
        title=build_title(material_type, topic, filename),
        topic=topic,
        source_filename=filename,
        document_id=document.id if document else None,
        content={
            "summary": summary_block,
            "key_concepts": _clean_concepts(raw.get("key_concepts"), settings.MAX_KEY_CONCEPTS),
            "definitions": _clean_definitions(raw.get("definitions"), settings.MAX_KEY_CONCEPTS + 4),
            "flashcards": _clean_flashcards(raw.get("flashcards"), settings.MAX_FLASHCARDS),
            "revision_notes": _clean_revision_notes(raw.get("revision_notes"), 10),
        },
    )

    if material.is_empty:
        raise InvalidAIResponseError(
            "The AI did not return usable study content for this document. "
            "Try a different topic or a longer document.",
            detail=f"empty study payload for type {material_type.value}",
        )

    return material


async def generate_study_material(
    *,
    indexed: IndexedDocument,
    material_type: StudyMaterialType,
    topic: str = "",
    generator: QuestionGeneratorService | None = None,
    persist: bool = True,
    user_id: str | None = None,
) -> StudyMaterial:
    """Generates, validates and persists one study resource bundle."""
    engine = generator or QuestionGeneratorService()

    query = default_retrieval_query(topic)
    context, chunks = indexed.retriever.build_context(query)
    if not context:
        context = indexed.text[: settings.RAG_MAX_CONTEXT_CHARS]

    raw = await run_generation(engine.generate_study_material, context, material_type.value, topic)

    material = normalize_study_payload(
        raw,
        material_type=material_type,
        topic=topic,
        filename=indexed.document.filename,
        document=indexed.document,
    )

    if persist:
        from services.database import async_save_study_material

        try:
            await async_save_study_material(
                material_id=material.id,
                material_type=material.material_type,
                title=material.title,
                content=material.content_payload(),
                topic=material.topic,
                source_filename=material.source_filename,
                document_id=material.document_id,
                user_id=user_id,
            )
        except Exception as exc:  # noqa: BLE001 - persistence must not lose the payload
            logger.warning("Study material could not be persisted: %s", exc)

    logger.info(
        "Generated %s study material for %s using %s context chunk(s)",
        material.material_type,
        indexed.document.filename,
        len(chunks),
    )
    return material


async def run_generation(func, *args):
    """Executes a blocking generator call off the event loop."""
    from services.documents import run_blocking

    try:
        return await run_blocking(func, *args)
    except GenerationError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalise unexpected provider failures
        logger.exception("Study material generation failed: %s", exc)
        raise GenerationError(
            "We could not generate study materials right now. Please try again.",
            detail=str(exc),
        ) from exc


def new_material_id() -> str:
    return str(uuid.uuid4())


__all__ = [
    "build_title",
    "generate_study_material",
    "new_material_id",
    "normalize_study_payload",
]