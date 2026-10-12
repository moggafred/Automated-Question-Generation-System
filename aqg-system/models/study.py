"""Schemas for AI-generated study and revision resources."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StudyMaterialType(str, Enum):
    """Supported study resource formats."""

    SUMMARY = "summary"
    KEY_CONCEPTS = "key-concepts"
    FLASHCARDS = "flashcards"
    DEFINITIONS = "definitions"
    REVISION_NOTES = "revision-notes"
    ALL = "all"

    @classmethod
    def values(cls) -> list[str]:
        return [item.value for item in cls]

    @classmethod
    def resolve(cls, raw: str | None) -> "StudyMaterialType | None":
        if not raw:
            return None
        key = str(raw).strip().lower().replace(" ", "-").replace("_", "-")
        aliases = {
            "summaries": cls.SUMMARY,
            "concept": cls.KEY_CONCEPTS,
            "keyconcept": cls.KEY_CONCEPTS,
            "key-concepts": cls.KEY_CONCEPTS,
            "concepts": cls.KEY_CONCEPTS,
            "flash-card": cls.FLASHCARDS,
            "flash-cards": cls.FLASHCARDS,
            "flashcard": cls.FLASHCARDS,
            "cards": cls.FLASHCARDS,
            "definition": cls.DEFINITIONS,
            "glossary": cls.DEFINITIONS,
            "revision": cls.REVISION_NOTES,
            "notes": cls.REVISION_NOTES,
            "revision-notes": cls.REVISION_NOTES,
            "everything": cls.ALL,
            "bundle": cls.ALL,
        }
        for candidate in cls:
            if candidate.value == key:
                return candidate
        return aliases.get(key)


STUDY_MATERIAL_LABELS: dict[str, str] = {
    StudyMaterialType.SUMMARY.value: "Summary",
    StudyMaterialType.KEY_CONCEPTS.value: "Key Concepts",
    StudyMaterialType.FLASHCARDS.value: "Flashcards",
    StudyMaterialType.DEFINITIONS.value: "Important Definitions",
    StudyMaterialType.REVISION_NOTES.value: "Revision Notes",
    StudyMaterialType.ALL.value: "Full Study Pack",
}


class KeyConcept(BaseModel):
    """A single named concept extracted from the document."""

    title: str = Field(..., min_length=1, max_length=160, description="Concept name.")
    description: str = Field(..., min_length=1, max_length=1200, description="What the concept means.")
    why_it_matters: str = Field("", max_length=600, description="Practical relevance of the concept.")


class Flashcard(BaseModel):
    """A front/back revision card."""

    front: str = Field(..., min_length=1, max_length=600, description="Prompt side of the card.")
    back: str = Field(..., min_length=1, max_length=1200, description="Answer side of the card.")
    hint: str = Field("", max_length=300, description="Optional memory aid.")
    topic: str = Field("", max_length=160, description="Concept the card reinforces.")


class Definition(BaseModel):
    """A term worth memorising with its document-grounded meaning."""

    term: str = Field(..., min_length=1, max_length=160, description="Defined term.")
    definition: str = Field(..., min_length=1, max_length=1200, description="Definition from the source.")
    example: str = Field("", max_length=600, description="Concrete example when available.")


class RevisionNote(BaseModel):
    """A structured revision note block."""

    heading: str = Field(..., min_length=1, max_length=200, description="Note heading.")
    body: str = Field(..., min_length=1, max_length=2000, description="Note content.")
    key_takeaway: str = Field("", max_length=600, description="Single most important takeaway.")


class Summary(BaseModel):
    """A concise document summary."""

    title: str = Field(default="Document Summary", max_length=240, description="Summary heading.")
    overview: str = Field(default="", max_length=4000, description="High-level orientation paragraph.")
    points: list[str] = Field(
        default_factory=list,
        description="Ordered bullet points capturing the essential content.",
    )
    learning_outcomes: list[str] = Field(
        default_factory=list,
        description="What a learner should be able to do after studying this.",
    )


class StudyMaterial(BaseModel):
    """A stored study resource bundle."""

    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Study material UUID4.")
    material_type: str = Field(..., max_length=40, description="Resource format identifier.")
    title: str = Field(..., max_length=240, description="Resource heading.")
    topic: str = Field(default="", max_length=200, description="Learner-supplied topic label.")
    source_filename: str | None = Field(None, max_length=255, description="Original upload name.")
    document_id: str | None = Field(None, max_length=64, description="Owning document record id.")
    summary: Summary | None = Field(None, description="Generated summary block.")
    key_concepts: list[KeyConcept] = Field(default_factory=list, description="Extracted concepts.")
    flashcards: list[Flashcard] = Field(default_factory=list, description="Generated revision cards.")
    definitions: list[Definition] = Field(default_factory=list, description="Generated glossary entries.")
    revision_notes: list[RevisionNote] = Field(default_factory=list, description="Generated revision notes.")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        description="ISO-8601 UTC creation timestamp.",
    )

    @field_validator("topic", "title", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @property
    def is_empty(self) -> bool:
        return not (
            (self.summary and (self.summary.overview or self.summary.points))
            or self.key_concepts
            or self.flashcards
            or self.definitions
            or self.revision_notes
        )

    def content_payload(self) -> dict[str, Any]:
        """The generated content only, which is what gets serialized to storage."""
        return {
            "summary": self.summary.model_dump(mode="json") if self.summary else None,
            "key_concepts": [item.model_dump(mode="json") for item in self.key_concepts],
            "flashcards": [item.model_dump(mode="json") for item in self.flashcards],
            "definitions": [item.model_dump(mode="json") for item in self.definitions],
            "revision_notes": [item.model_dump(mode="json") for item in self.revision_notes],
        }

    @classmethod
    def from_content(
        cls,
        *,
        material_type: str,
        title: str,
        content: dict[str, Any],
        topic: str = "",
        source_filename: str | None = None,
        document_id: str | None = None,
        material_id: str | None = None,
        created_at: str | None = None,
    ) -> "StudyMaterial":
        content = content or {}
        payload: dict[str, Any] = {
            "material_type": material_type,
            "title": title,
            "topic": topic,
            "source_filename": source_filename,
            "document_id": document_id,
            "summary": Summary.model_validate(content["summary"]) if content.get("summary") else None,
            "key_concepts": [KeyConcept.model_validate(item) for item in content.get("key_concepts") or []],
            "flashcards": [Flashcard.model_validate(item) for item in content.get("flashcards") or []],
            "definitions": [Definition.model_validate(item) for item in content.get("definitions") or []],
            "revision_notes": [RevisionNote.model_validate(item) for item in content.get("revision_notes") or []],
        }
        if material_id:
            payload["id"] = material_id
        if created_at:
            payload["created_at"] = created_at
        return cls.model_validate(payload)


__all__ = [
    "Definition",
    "Flashcard",
    "KeyConcept",
    "RevisionNote",
    "STUDY_MATERIAL_LABELS",
    "StudyMaterial",
    "StudyMaterialType",
    "Summary",
]