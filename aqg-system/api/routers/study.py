"""Study material generation and retrieval endpoints."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, UploadFile

from config.settings import settings
from errors import StudyMaterialNotFoundError, ValidationError
from models.study import STUDY_MATERIAL_LABELS, StudyMaterial, StudyMaterialType
from services.database import (
    async_count_study_materials,
    async_delete_study_material,
    async_get_study_material,
    async_list_study_materials,
)
from services.documents import ingest_document
from services.generation import resolve_instructions, resolve_topic
from services.generator import QuestionGeneratorService
from services.study_materials import generate_study_material

router = APIRouter(prefix="/api", tags=["study materials"])

generator_service = QuestionGeneratorService()


def _to_record(stored: dict) -> dict:
    """Rebuilds a full :class:`StudyMaterial` from a persistence-layer row.

    ``material_id`` is echoed alongside ``id`` so the single-resource endpoint and
    the listing endpoint agree on how a material is addressed.
    """
    record = StudyMaterial.from_content(
        material_type=stored["material_type"],
        title=stored["title"],
        content=stored["content"],
        topic=stored["topic"],
        source_filename=stored["source_filename"],
        document_id=stored["document_id"],
        material_id=stored["material_id"],
        created_at=stored["created_at"],
    ).model_dump(mode="json")
    record["material_id"] = record["id"]
    return record


@router.post("/generate-study-material", summary="Generate study resources from a document")
async def generate_study_material_endpoint(
    file: UploadFile = File(..., description="A PDF or TXT learning material."),
    type: str = Form("all", description="summary, key-concepts, flashcards, definitions, revision-notes or all."),
    topic: str = Form("", description="Optional topic focus for retrieval."),
) -> dict:
    """Generates and persists a study resource bundle grounded in the document."""
    material_type = StudyMaterialType.resolve(type)
    if material_type is None:
        supported = ", ".join(STUDY_MATERIAL_LABELS.keys())
        raise ValidationError(f"That study material type is not supported. Choose one of: {supported}.")

    resolved_topic = resolve_topic(topic)
    indexed = await ingest_document(file)

    material = await generate_study_material(
        indexed=indexed,
        material_type=material_type,
        topic=resolved_topic,
        generator=generator_service,
    )

    return {
        "material": material.model_dump(mode="json"),
        "label": STUDY_MATERIAL_LABELS.get(material.material_type, "Study Material"),
        "document": indexed.document.model_dump(mode="json"),
    }


@router.get("/study-materials", summary="List stored study materials")
async def list_study_materials_endpoint(
    limit: int = Query(20, ge=1, le=200, description="Maximum number of records to return."),
    offset: int = Query(0, ge=0, description="Pagination offset."),
    type: str = Query("", description="Optional material type filter."),
) -> dict:
    """Returns stored study materials, newest first."""
    normalized = (type or "").strip()
    if normalized:
        resolved = StudyMaterialType.resolve(normalized)
        normalized = resolved.value if resolved else normalized

    records = await async_list_study_materials(limit=limit, offset=offset, material_type=normalized)
    total = await async_count_study_materials()

    return {
        "total": total,
        "count": len(records),
        "limit": limit,
        "offset": offset,
        "materials": [
            {
                "material_id": record["material_id"],
                "document_id": record["document_id"],
                "topic": record["topic"],
                "material_type": record["material_type"],
                "label": STUDY_MATERIAL_LABELS.get(record["material_type"], "Study Material"),
                "title": record["title"],
                "source_filename": record["source_filename"],
                "created_at": record["created_at"],
            }
            for record in records
        ],
    }


@router.get("/study-materials/{material_id}", summary="Retrieve one study material")
async def get_study_material_endpoint(material_id: str) -> dict:
    """Returns the full generated content for a stored study material."""
    stored = await async_get_study_material(material_id)
    if stored is None:
        raise StudyMaterialNotFoundError()

    record = _to_record(stored)
    return {
        "material": record,
        "label": STUDY_MATERIAL_LABELS.get(record["material_type"], "Study Material"),
    }


@router.delete("/study-materials/{material_id}", summary="Delete a study material")
async def delete_study_material_endpoint(material_id: str) -> dict:
    """Removes a stored study material."""
    deleted = await async_delete_study_material(material_id)
    if not deleted:
        raise StudyMaterialNotFoundError()
    return {"material_id": material_id, "deleted": True}


@router.get("/study-types", summary="Supported study material types")
async def study_types() -> dict:
    """Returns the study resource vocabulary for the client."""
    return {
        "types": [
            {"value": value, "label": label}
            for value, label in STUDY_MATERIAL_LABELS.items()
            if value != StudyMaterialType.ALL.value
        ],
        "max_flashcards": settings.MAX_FLASHCARDS,
        "max_concepts": settings.MAX_KEY_CONCEPTS,
    }