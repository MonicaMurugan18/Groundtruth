"""Document text extraction and chunking.

Chunk boundaries directly determine what the evaluator gets to see, so this
stage matters for reliability, not just retrieval quality: a chunk that splits a
policy statement from its qualifier ("within 7 days", "for unopened items") can
make a correct answer look unsupported, or an incomplete answer look grounded.
Recursive splitting on paragraph boundaries with overlap is used to keep such
statements intact.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf"}


class UnsupportedDocument(ValueError):
    """Raised for a file type the ingester cannot read."""


@dataclass(slots=True)
class Chunk:
    """One indexed unit of text."""

    id: str
    text: str
    source: str
    index: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "metadata": {
                **self.metadata,
                "source": self.source,
                "chunk_index": self.index,
            },
        }


def extract_text(path: Path) -> str:
    """Read a document into plain text."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedDocument(
            f"Unsupported file type {suffix!r}. Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )

    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = [(page.extract_text() or "") for page in reader.pages]
        text = "\n\n".join(pages)
        if not text.strip():
            raise UnsupportedDocument(
                f"No extractable text in {path.name}. It may be a scanned PDF, "
                "which needs OCR before ingestion."
            )
        return text

    return path.read_text(encoding="utf-8", errors="replace")


def chunk_text(text: str, source: str, *, doc_id: str | None = None) -> list[Chunk]:
    """Split ``text`` into overlapping chunks with stable, content-derived ids."""
    # Imported here, not at module scope, because langchain_text_splitters
    # eagerly imports its sentence_transformers submodule, which pulls in
    # torch and transformers - measured at 34.5s of the 48s it took to import
    # app.main. Uvicorn imports the app before it opens the listening socket,
    # so that cost was paid before the port existed and the platform's port
    # scan timed out. Deferring it to the first chunking call keeps splitting
    # behaviour identical. Same pattern as pypdf in extract_text above.
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    settings = get_settings()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
        length_function=len,
    )
    pieces = [piece.strip() for piece in splitter.split_text(text) if piece.strip()]

    chunks: list[Chunk] = []
    for index, piece in enumerate(pieces):
        # Content-derived id means re-ingesting an unchanged document produces
        # the same ids, so Moss and FAISS upserts stay idempotent.
        digest = hashlib.sha1(f"{source}:{index}:{piece}".encode()).hexdigest()[:16]
        chunks.append(
            Chunk(
                id=digest,
                text=piece,
                source=source,
                index=index,
                metadata={"doc_id": doc_id or source},
            )
        )

    logger.info("Chunked %r into %d chunks", source, len(chunks))
    return chunks


def chunk_document(path: Path, *, doc_id: str | None = None) -> list[Chunk]:
    """Extract and chunk a document from disk."""
    return chunk_text(extract_text(path), source=path.name, doc_id=doc_id)
