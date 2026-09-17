"""Document ingestion: file to indexed chunks.

Pipeline: extract text -> chunk with overlap -> embed -> index into FAISS and,
when configured, into Moss.

Both indexes are written so the similarity signal used by context validation is
always available, even when Moss serves retrieval. Failure to index into Moss is
recorded on the document row and surfaced to the caller rather than swallowed -
a half-indexed corpus is a common and confusing cause of retrieval failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.integrations.moss.client import (
    MossNotConfigured,
    MossUnavailable,
    get_moss_retriever,
)
from app.models.document import IngestedDocument
from app.retrieval.chunking import UnsupportedDocument, chunk_document, chunk_text
from app.retrieval.faiss_store import get_faiss_store

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestionResult:
    document_id: str
    filename: str
    chunk_count: int
    indexed_faiss: int
    indexed_moss: int
    moss_status: str
    warnings: list[str] = field(default_factory=list)


async def ingest_file(
    path: Path,
    *,
    db: AsyncSession,
    original_name: str | None = None,
    content_type: str = "text/plain",
) -> IngestionResult:
    """Ingest a document from disk into the retrieval corpus."""
    name = original_name or path.name
    try:
        chunks = chunk_document(path, doc_id=name)
    except UnsupportedDocument:
        raise
    return await _index_chunks(
        chunks=[chunk.to_dict() for chunk in chunks],
        filename=name,
        content_type=content_type,
        size_bytes=path.stat().st_size if path.exists() else 0,
        db=db,
    )


async def ingest_raw_text(
    text: str,
    *,
    db: AsyncSession,
    name: str,
) -> IngestionResult:
    """Ingest a plain-text document supplied directly in the request body.

    Used by the reliability test fixtures, which need a corpus with known
    contents in order to assert on retrieval behaviour.
    """
    chunks = chunk_text(text, source=name, doc_id=name)
    return await _index_chunks(
        chunks=[chunk.to_dict() for chunk in chunks],
        filename=name,
        content_type="text/plain",
        size_bytes=len(text.encode("utf-8")),
        db=db,
    )


async def _index_chunks(
    *,
    chunks: list[dict],
    filename: str,
    content_type: str,
    size_bytes: int,
    db: AsyncSession,
) -> IngestionResult:
    warnings: list[str] = []
    settings = get_settings()

    if not chunks:
        raise UnsupportedDocument(
            f"{filename} produced no text chunks. It may be empty or unreadable."
        )

    # --- FAISS (always) ---
    store = get_faiss_store()
    indexed_faiss = store.add_chunks(chunks)
    if indexed_faiss == 0:
        # Chunk ids are content-derived, so re-ingesting an unchanged document
        # is a no-op. Say so explicitly: "0 indexed" otherwise reads like a
        # failure when it actually means "already present".
        warnings.append(
            f"All {len(chunks)} chunks were already in the FAISS index, so nothing "
            "was re-embedded. Re-ingesting an unchanged document is a no-op."
        )

    # --- Moss (when configured) ---
    indexed_moss = 0
    moss_status = "skipped"
    if settings.moss_configured:
        retriever = get_moss_retriever()
        try:
            # add_docs requires an existing index; create it on first ingest.
            try:
                await retriever.ensure_loaded()
                indexed_moss = await retriever.add_documents(chunks)
                moss_status = "updated"
            except MossUnavailable:
                result = await retriever.create_index(chunks)
                indexed_moss = int(result.get("doc_count") or len(chunks))
                moss_status = "created"
        except MossNotConfigured as exc:
            moss_status = "not_configured"
            warnings.append(str(exc))
        except MossUnavailable as exc:
            moss_status = "failed"
            warnings.append(
                f"Indexing into Moss failed, so Moss retrieval will not see this "
                f"document: {exc}"
            )
            logger.warning("Moss indexing failed for %s: %s", filename, exc)
    else:
        moss_status = "not_configured"
        warnings.append(
            "Moss is not configured, so this document was indexed into FAISS only."
        )

    document = IngestedDocument(
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        chunk_count=len(chunks),
        indexed_faiss=indexed_faiss > 0,
        indexed_moss=indexed_moss > 0,
        status="indexed" if indexed_faiss or indexed_moss else "failed",
        error="; ".join(warnings) if warnings else None,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    logger.info(
        "Ingested %s: %d chunks (faiss=%d, moss=%d/%s)",
        filename,
        len(chunks),
        indexed_faiss,
        indexed_moss,
        moss_status,
    )

    return IngestionResult(
        document_id=document.id,
        filename=filename,
        chunk_count=len(chunks),
        indexed_faiss=indexed_faiss,
        indexed_moss=indexed_moss,
        moss_status=moss_status,
        warnings=warnings,
    )
