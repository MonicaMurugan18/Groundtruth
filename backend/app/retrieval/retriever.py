"""Unified retrieval across Moss and FAISS.

Moss is the primary backend per the architecture. FAISS is the fallback used
when Moss is unconfigured or erroring.

The backend that actually served each request is recorded on the trace and
returned to the caller. That matters for the integrity of the dashboard: a
FAISS-served result is never presented as a Moss result, and a Moss outage
appears as a visible warning rather than a silent downgrade.

Similarity scores are always attached, even for Moss hits, because context
validation and the trace view need a comparable relevance number. Moss returns
its own score on its own scale, so an embedding cosine is computed alongside it
for consistency across backends.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config.settings import Settings, get_settings
from app.integrations.moss.client import (
    MossNotConfigured,
    MossUnavailable,
    get_moss_retriever,
)
from app.retrieval.faiss_store import get_faiss_store
from app.schemas.common import RetrievalBackend
from app.schemas.evaluation import RetrievedChunk
from app.tracing.timer import RETRIEVAL, LatencyTrace

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RetrievalOutcome:
    chunks: list[RetrievedChunk]
    backend: RetrievalBackend
    warnings: list[str] = field(default_factory=list)
    # Moss's self-reported search duration, when Moss served the request.
    engine_ms: float | None = None

    @property
    def texts(self) -> list[str]:
        return [chunk.text for chunk in self.chunks]

    @property
    def similarities(self) -> list[float]:
        return [chunk.score for chunk in self.chunks if chunk.score is not None]


async def retrieve(
    query: str,
    *,
    top_k: int | None = None,
    trace: LatencyTrace | None = None,
    settings: Settings | None = None,
) -> RetrievalOutcome:
    """Retrieve context for ``query``, preferring Moss."""
    settings = settings or get_settings()
    k = top_k or settings.retrieval_top_k
    warnings: list[str] = []

    prefer_moss = settings.retrieval_backend.lower() == "moss"

    if prefer_moss:
        try:
            outcome = await _retrieve_moss(query, k, trace)
            if outcome.chunks:
                return outcome
            warnings.append(
                "Moss returned no matches; falling back to FAISS for this query."
            )
        except MossNotConfigured:
            warnings.append(
                "Moss is not configured (MOSS_PROJECT_ID / MOSS_PROJECT_KEY are unset). "
                "Retrieval was served by FAISS."
            )
        except MossUnavailable as exc:
            logger.warning("Moss retrieval failed, falling back to FAISS: %s", exc)
            warnings.append(f"Moss retrieval failed, so FAISS served this query: {exc}")

    outcome = _retrieve_faiss(query, k, trace)
    outcome.warnings = warnings + outcome.warnings
    return outcome


async def _retrieve_moss(
    query: str, k: int, trace: LatencyTrace | None
) -> RetrievalOutcome:
    """Search Moss and normalise its hits."""
    retriever = get_moss_retriever()

    if trace is not None:
        with trace.span(RETRIEVAL):
            result = await retriever.search(query, top_k=k)
    else:
        result = await retriever.search(query, top_k=k)

    texts = [hit.text for hit in result.hits]
    # Comparable cosine similarity, so the number shown next to a Moss chunk
    # means the same thing as the one shown next to a FAISS chunk.
    cosines = get_faiss_store().score_texts(query, texts) if texts else []

    chunks = [
        RetrievedChunk(
            text=hit.text,
            score=cosines[index] if index < len(cosines) else None,
            source=hit.metadata.get("source"),
            chunk_id=hit.metadata.get("doc_id"),
            metadata={**hit.metadata, "moss_score": hit.score},
        )
        for index, hit in enumerate(result.hits)
    ]

    return RetrievalOutcome(
        chunks=chunks,
        backend=RetrievalBackend.MOSS,
        engine_ms=result.time_taken_ms,
    )


def _retrieve_faiss(query: str, k: int, trace: LatencyTrace | None) -> RetrievalOutcome:
    """Search the local FAISS index."""
    store = get_faiss_store()

    if trace is not None:
        with trace.span(RETRIEVAL):
            hits = store.search(query, top_k=k)
    else:
        hits = store.search(query, top_k=k)

    chunks = [
        RetrievedChunk(
            text=hit.text,
            score=hit.score,
            source=hit.source,
            chunk_id=hit.chunk_id,
            metadata=hit.metadata,
        )
        for hit in hits
    ]

    warnings: list[str] = []
    backend = RetrievalBackend.FAISS
    if not chunks:
        backend = RetrievalBackend.NONE
        if store.size == 0:
            warnings.append(
                "The document corpus is empty. Ingest documents via POST /ingest "
                "before querying."
            )

    return RetrievalOutcome(chunks=chunks, backend=backend, warnings=warnings)
