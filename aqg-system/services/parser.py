"""PDF/TXT text extraction and overlapping-window chunking."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import fitz  # PyMuPDF

from config.settings import settings
from errors import DocumentParseError, EmptyDocumentError
from models.document import validate_extension

_WHITESPACE_RUN = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(slots=True)
class ParsedPayload:
    """Raw extraction result plus the metrics used for document metadata."""

    text: str
    page_count: int = 0
    word_count: int = 0
    character_count: int = 0
    warnings: list[str] = field(default_factory=list)


class DocumentParserService:
    """Stateless helpers for turning an upload into retrievable text chunks."""

    @staticmethod
    def extract_text(file_bytes: bytes, filename: str) -> str:
        """Extracts raw text from an uploaded PDF or TXT document.

        Raises a user-facing :class:`~errors.DocumentError` subclass on every
        failure path so the API never has to leak library internals.
        """
        return DocumentParserService.extract(file_bytes, filename).text

    @staticmethod
    def extract(file_bytes: bytes, filename: str) -> ParsedPayload:
        """Extracts text and returns it together with document metrics."""
        extension = validate_extension(filename, settings.allowed_extensions)

        if not file_bytes:
            raise EmptyDocumentError()

        if extension == ".txt":
            text = DocumentParserService._decode_text(file_bytes)
            return DocumentParserService._build_payload(text, page_count=1)

        text, page_count = DocumentParserService._extract_pdf(file_bytes)
        return DocumentParserService._build_payload(text, page_count=page_count)

    # -- Internals -------------------------------------------------------
    @staticmethod
    def _decode_text(file_bytes: bytes) -> str:
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return file_bytes.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        raise DocumentParseError(
            "We could not decode that text file. Please re-save it as UTF-8 and try again."
        )

    @staticmethod
    def _extract_pdf(file_bytes: bytes) -> tuple[str, int]:
        document = None
        try:
            document = fitz.open(stream=file_bytes, filetype="pdf")
            if document.needs_pass:
                raise DocumentParseError(
                    "This PDF is password protected. Please upload an unlocked copy."
                )

            page_count = document.page_count
            pages: list[str] = []
            for index in range(page_count):
                try:
                    pages.append(document.load_page(index).get_text("text") or "")
                except Exception:  # noqa: BLE001 - skip individual unreadable pages
                    continue

            text = "\n\n".join(pages)
        except DocumentParseError:
            raise
        except Exception as exc:  # noqa: BLE001 - PyMuPDF raises many error types
            raise DocumentParseError(
                "We could not read that PDF. It may be corrupted or not a real PDF file."
            ) from exc
        finally:
            if document is not None:
                try:
                    document.close()
                except Exception:  # noqa: BLE001 - closing must never mask the real error
                    pass

        return text, page_count

    @staticmethod
    def _build_payload(text: str, page_count: int) -> ParsedPayload:
        normalized = _BLANK_LINES.sub("\n\n", _WHITESPACE_RUN.sub(" ", text or "")).strip()
        if not normalized.strip():
            raise EmptyDocumentError()

        word_count = len(normalized.split())
        if word_count < settings.MIN_DOCUMENT_WORDS:
            raise EmptyDocumentError(
                "We need a little more text to work with. Please upload a document that "
                "contains a few paragraphs of readable content."
            )

        return ParsedPayload(
            text=normalized,
            page_count=max(1, page_count),
            word_count=word_count,
            character_count=len(normalized),
        )

    @staticmethod
    def chunk_text(
        text: str,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> list[str]:
        """Splits text into overlapping word windows to protect context boundaries."""
        words = (text or "").split()
        if not words:
            return []

        size = chunk_size or settings.RAG_CHUNK_SIZE
        stride = overlap if overlap is not None else settings.RAG_CHUNK_OVERLAP
        size = max(20, int(size))
        stride = max(0, min(int(stride), size - 1))

        chunks: list[str] = []
        start = 0
        while start < len(words):
            window = words[start : start + size]
            if not window:
                break
            chunks.append(" ".join(window))
            if start + size >= len(words):
                break
            start += size - stride

        return chunks

    @staticmethod
    def build_index_payload(file_bytes: bytes, filename: str) -> tuple[ParsedPayload, list[str]]:
        """Convenience wrapper returning both the parsed payload and its chunks."""
        payload = DocumentParserService.extract(file_bytes, filename)
        chunks = DocumentParserService.chunk_text(payload.text)
        return payload, chunks


__all__ = ["DocumentParserService", "ParsedPayload"]