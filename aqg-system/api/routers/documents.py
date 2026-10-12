"""Ingested document browsing endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from config.settings import settings
from services.database import async_count_documents, async_list_documents

router = APIRouter(prefix="/api", tags=["documents"])


@router.get("/documents", summary="List processed documents")
async def list_documents(
    limit: int = Query(20, ge=1, le=200, description="Maximum number of documents to return."),
    offset: int = Query(0, ge=0, description="Pagination offset."),
) -> dict:
    """Returns ingested documents with the metrics recorded at upload time."""
    rows = await async_list_documents(limit=limit, offset=offset)
    total = await async_count_documents()

    return {
        "total": total,
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "documents": [
            {
                "document_id": row["id"],
                "filename": row["filename"],
                "extension": row["extension"],
                "size_bytes": row["size_bytes"],
                "page_count": row["page_count"],
                "word_count": row["word_count"],
                "chunk_count": row["chunk_count"],
                "status": row["status"],
                "created_at": row["created_at"],
            }
            for row in rows
        ],
        "limits": {
            "max_upload_mb": settings.max_upload_size_mb,
            "allowed_extensions": list(settings.allowed_extensions),
        },
    }