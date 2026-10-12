"""Schemas describing an ingested source document."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from errors import UnsupportedFileTypeError


class ParsedDocument(BaseModel):
    """The result of extracting and chunking an uploaded file."""

    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Document record UUID4.")
    filename: str = Field(..., min_length=1, max_length=255, description="Original uploaded filename.")
    extension: str = Field(..., max_length=10, description="Lower-cased file extension.")
    size_bytes: int = Field(0, ge=0, description="Size of the upload in bytes.")
    page_count: int = Field(0, ge=0, description="Pages for PDFs, or 1 for plain text.")
    character_count: int = Field(0, ge=0, description="Extracted character count.")
    word_count: int = Field(0, ge=0, description="Extracted word count.")
    chunk_count: int = Field(0, ge=0, description="Number of RAG chunks produced.")
    status: str = Field("ready", max_length=30, description="Processing status.")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        description="ISO-8601 UTC ingestion timestamp.",
    )

    @property
    def size_display(self) -> str:
        return humanize_bytes(self.size_bytes)


class DocumentSummary(BaseModel):
    """Lightweight document row used by history lists and the dashboard."""

    model_config = ConfigDict(use_enum_values=True)

    document_id: str = Field(..., description="Document UUID4.")
    filename: str = Field(..., description="Original uploaded filename.")
    extension: str = Field(default="", description="File extension.")
    size_bytes: int = Field(0, ge=0, description="Upload size in bytes.")
    page_count: int = Field(0, ge=0, description="Page count.")
    word_count: int = Field(0, ge=0, description="Word count.")
    chunk_count: int = Field(0, ge=0, description="Indexed chunk count.")
    status: str = Field("ready", description="Processing status.")
    created_at: str = Field(..., description="ISO-8601 UTC ingestion timestamp.")


def humanize_bytes(size: int | float) -> str:
    """Formats a byte count for display, e.g. ``2.4 MB``."""
    value = float(size or 0)
    if value < 1024:
        return f"{int(value)} B"
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} GB"


def validate_extension(filename: str, allowed: tuple[str, ...]) -> str:
    """Returns the validated lower-cased extension or raises a friendly error."""
    name = (filename or "").strip()
    if not name:
        raise UnsupportedFileTypeError()
    extension = f".{name.rsplit('.', 1)[-1].lower()}" if "." in name else ""
    if extension not in allowed:
        supported = ", ".join(allowed)
        raise UnsupportedFileTypeError(
            f"That file type is not supported. Please upload one of: {supported}."
        )
    return extension


__all__ = ["DocumentSummary", "ParsedDocument", "humanize_bytes", "validate_extension"]