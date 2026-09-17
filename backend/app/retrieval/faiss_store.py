"""Persistent FAISS vector store.

Serves two roles in the architecture:

1. The secondary retrieval backend, used when Moss is not configured. A trace
   produced this way is labelled ``retrieval_backend="faiss"`` so the dashboard
   never attributes FAISS results to Moss.
2. The source of the similarity signal used by context validation, which needs a
   numeric relevance measure even when Moss served the retrieval.

Because embeddings are L2-normalised, an ``IndexFlatIP`` inner-product search
returns cosine similarity directly.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.config.settings import get_settings
from app.retrieval.embeddings import embed_query, embed_texts, embedding_dimension

logger = logging.getLogger(__name__)

INDEX_FILENAME = "groundtruth.index"
METADATA_FILENAME = "groundtruth_meta.json"


@dataclass(slots=True)
class FaissHit:
    text: str
    score: float
    source: str | None
    chunk_id: str | None
    metadata: dict[str, Any]


class FaissStore:
    """A small, persistent, thread-safe FAISS index over document chunks."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._dir = self._settings.faiss_path
        self._index: Any | None = None
        self._records: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._loaded = False

    # -- Persistence -----------------------------------------------------

    @property
    def _index_path(self) -> Path:
        return self._dir / INDEX_FILENAME

    @property
    def _meta_path(self) -> Path:
        return self._dir / METADATA_FILENAME

    def _new_index(self) -> Any:
        import faiss

        return faiss.IndexFlatIP(embedding_dimension())

    def load(self) -> None:
        """Load the index from disk, or start an empty one."""
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            import faiss

            self._dir.mkdir(parents=True, exist_ok=True)
            if self._index_path.exists() and self._meta_path.exists():
                try:
                    self._index = faiss.read_index(str(self._index_path))
                    self._records = json.loads(
                        self._meta_path.read_text(encoding="utf-8")
                    )
                    logger.info("FAISS index loaded (%d vectors)", self._index.ntotal)
                except Exception:
                    # A corrupt index must not take the API down; rebuild empty
                    # and let re-ingestion repopulate it.
                    logger.exception("FAISS index unreadable; starting empty")
                    self._index = self._new_index()
                    self._records = []
            else:
                self._index = self._new_index()
                self._records = []
            self._loaded = True

    def _persist(self) -> None:
        import faiss

        self._dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self._index_path))
        self._meta_path.write_text(
            json.dumps(self._records, ensure_ascii=False), encoding="utf-8"
        )

    # -- Mutation --------------------------------------------------------

    def add_chunks(self, chunks: list[dict[str, Any]]) -> int:
        """Embed and index chunks, skipping ids already present."""
        self.load()
        if not chunks:
            return 0

        with self._lock:
            known = {record["id"] for record in self._records}
            fresh = [chunk for chunk in chunks if chunk["id"] not in known]
            if not fresh:
                logger.info("All %d chunks already indexed in FAISS", len(chunks))
                return 0

            vectors = embed_texts([chunk["text"] for chunk in fresh])
            self._index.add(vectors)
            for chunk in fresh:
                metadata = chunk.get("metadata") or {}
                self._records.append(
                    {
                        "id": chunk["id"],
                        "text": chunk["text"],
                        "source": metadata.get("source"),
                        "metadata": metadata,
                    }
                )
            self._persist()
            logger.info("Added %d chunks to FAISS (total %d)", len(fresh), self._index.ntotal)
            return len(fresh)

    def clear(self) -> None:
        """Drop every vector. Used by the reset endpoint and the test harness."""
        with self._lock:
            self._index = self._new_index()
            self._records = []
            self._loaded = True
            self._persist()
            logger.info("FAISS index cleared")

    # -- Query -----------------------------------------------------------

    @property
    def size(self) -> int:
        self.load()
        return len(self._records)

    def search(self, query: str, top_k: int | None = None) -> list[FaissHit]:
        """Return the ``top_k`` most similar chunks, highest cosine first."""
        self.load()
        if not self._records:
            return []

        k = min(top_k or self._settings.retrieval_top_k, len(self._records))
        scores, indices = self._index.search(embed_query(query), k)

        hits: list[FaissHit] = []
        for score, position in zip(scores[0], indices[0], strict=False):
            # FAISS returns -1 for empty slots when k exceeds the vector count.
            if position < 0 or position >= len(self._records):
                continue
            record = self._records[int(position)]
            hits.append(
                FaissHit(
                    text=record["text"],
                    score=float(np.clip(float(score), -1.0, 1.0)),
                    source=record.get("source"),
                    chunk_id=record.get("id"),
                    metadata=record.get("metadata") or {},
                )
            )
        return hits

    def score_texts(self, query: str, texts: list[str]) -> list[float]:
        """Cosine similarity between ``query`` and arbitrary texts.

        Lets context validation produce a similarity signal for context that
        came from Moss and is therefore absent from this index.
        """
        if not texts:
            return []
        query_vector = embed_query(query)[0]
        text_vectors = embed_texts(texts)
        return [
            float(np.clip(float(np.dot(query_vector, vector)), -1.0, 1.0))
            for vector in text_vectors
        ]


_store: FaissStore | None = None


def get_faiss_store() -> FaissStore:
    global _store
    if _store is None:
        _store = FaissStore()
    return _store
