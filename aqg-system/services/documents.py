"""Document ingestion pipeline: upload bytes -> text -> chunks -> indexed retriever."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from config.settings import settings
from errors import EmptyDocumentError, FileTooLargeError
from models.document import ParsedDocument, validate_extension
from services.database import async_save_document
from services.parser import DocumentParserService
from services.retriever import DocumentRetriever, RetrievedChunk

logger = logging.getLogger("aqg.documents")

MAX_UPLOAD_CHUNK_BYTES = 1024 * 1024


@dataclass(slots=True)
class IndexedDocument:
    """A fully processed upload plus its live retrieval index."""

    document: ParsedDocument
    retriever: DocumentRetriever
    text: str

    @property
    def document_id(self) -> str:
        return self.document.id

    @property
    def chunk_count(self) -> int:
        return self.document.chunk_count


async def read_upload_bytes(upload) -> bytes:
    """Reads an ``UploadFile`` in bounded chunks, enforcing ``MAX_UPLOAD_SIZE``.

    The stream is consumed incrementally so an oversized upload is rejected
    without buffering the whole payload into memory.
    """
    if upload is None:
        raise EmptyDocumentError("No document was uploaded.")

    limit = int(settings.MAX_UPLOAD_SIZE)
    buffer = bytearray()
    read_size = min(MAX_UPLOAD_CHUNK_BYTES, max(limit, 1))

    while True:
        chunk = await upload.read(read_size)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise file_too_large_error(settings.max_upload_size_mb)

    if not buffer:
        raise EmptyDocumentError("The uploaded file is empty.")

    return bytes(buffer)


def file_too_large_error(size_mb: int):
    """Builds the typed 413 error raised for an oversized upload."""
    return FileTooLargeError(
        f"That file is larger than the {size_mb} MB limit. Please choose a smaller document."
    )


async def ingest_document(
    upload,
    *,
    persist: bool = True,
    file_bytes: bytes | None = None,
    user_id: str | None = None,
) -> IndexedDocument:
    """Runs the full ingestion pipeline for one uploaded document.

    Steps: validate -> extract text -> chunk -> index -> persist metadata.
    """
    filename = getattr(upload, "filename", None) or "document.txt"
    validate_extension(filename, settings.allowed_extensions)

    payload_bytes = file_bytes if file_bytes is not None else await read_upload_bytes(upload)

    parsed, chunks = await run_blocking(DocumentParserService.build_index_payload, payload_bytes, filename)

    if not chunks:
        raise EmptyDocumentError(
            "We could not break that document into usable sections. Please try another file."
        )

    retriever = await run_blocking(build_retriever, chunks)

    document = ParsedDocument(
        id=str(uuid.uuid4()),
        filename=filename,
        extension=filename.rsplit(".", 1)[-1].lower() if "." in filename else "",
        size_bytes=len(payload_bytes),
        page_count=parsed.page_count,
        character_count=parsed.character_count,
        word_count=parsed.word_count,
        chunk_count=len(chunks),
        status="ready",
    )

    if persist:
        try:
            await async_save_document(
                document_id=document.id,
                filename=document.filename,
                extension=document.extension,
                size_bytes=document.size_bytes,
                page_count=document.page_count,
                character_count=document.character_count,
                word_count=document.word_count,
                chunk_count=document.chunk_count,
                status=document.status,
                user_id=user_id,
            )
        except Exception as exc:  # noqa: BLE001 - persistence must not break generation
            logger.warning("Document metadata could not be persisted: %s", exc)

    logger.info(
        "Ingested %s (%s words, %s chunks)", document.filename, document.word_count, document.chunk_count
    )
    return IndexedDocument(document=document, retriever=retriever, text=parsed.text)


def build_retriever(chunks: list[str]) -> DocumentRetriever:
    """Builds and indexes a retriever for the supplied chunks."""
    retriever = DocumentRetriever(dim=settings.RAG_EMBED_DIM)
    retriever.index_chunks(chunks)
    return retriever


async def run_blocking(func, *args):
    """Runs a CPU-bound callable in a worker thread so the event loop stays free."""
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(func, *args)


def grounding_reference(chunks: list[RetrievedChunk]) -> str:
    """Builds a compact citation string appended to each generated item."""
    if not chunks:
        return ""
    preview = " ".join(chunks[0].text.strip().split())[:220]
    label = "Context section" if len(chunks) == 1 else f"Context sections ({len(chunks)})"
    return f"{label}: {preview}"


__all__ = [
    "IndexedDocument",
    "build_retriever",
    "grounding_reference",
    "ingest_document",
    "read_upload_bytes",
    "run_blocking",
]