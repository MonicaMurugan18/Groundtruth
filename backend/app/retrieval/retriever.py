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
    MossStage,
    MossStageRecord,
    MossStatus,
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
    # Auditable record of the Moss call behind this retrieval, present whenever
    # Moss was reached for (or deliberately skipped on) this query.
    moss_record: MossStageRecord | None = None

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

    # Honour the *passed* settings, not just the process-wide singleton. The
    # Moss adapter is a module-level singleton built from the environment, so
    # without this check a caller that supplies settings with no Moss
    # credentials would still be served by Moss.
    if prefer_moss and not settings.moss_configured:
        prefer_moss = False
        warnings.append(
            "Moss is not configured (MOSS_PROJECT_ID / MOSS_PROJECT_KEY are unset). "
            "Retrieval was served by FAISS."
        )

    moss_record: MossStageRecord | None = None

    if prefer_moss:
        outcome, moss_record = await _retrieve_moss(query, k, trace)
        if outcome is not None and outcome.chunks:
            return outcome
        if moss_record.status is MossStatus.EMPTY:
            warnings.append(
                "Moss returned no matches; falling back to FAISS for this query."
            )
        elif moss_record.status is MossStatus.NOT_CONFIGURED:
            warnings.append(
                "Moss is not configured (MOSS_PROJECT_ID / MOSS_PROJECT_KEY are unset). "
                "Retrieval was served by FAISS."
            )
        elif moss_record.status is MossStatus.FAILED:
            logger.warning(
                "Moss retrieval failed, falling back to FAISS: %s", moss_record.error
            )
            warnings.append(
                f"Moss retrieval failed, so FAISS served this query: {moss_record.error}"
            )
    else:
        # Distinguish the two reasons Moss was not called. "Not configured" is
        # a missing credential the operator can fix; "skipped" is a deliberate
        # choice of backend. Collapsing them into one status would make the
        # dashboard say "skipped" for what is really a setup problem.
        misconfigured = settings.retrieval_backend.lower() == "moss"
        moss_record = MossStageRecord(
            stage=MossStage.PRIMARY_RETRIEVAL,
            status=MossStatus.NOT_CONFIGURED if misconfigured else MossStatus.SKIPPED,
            query=query,
            error=(
                "MOSS_PROJECT_ID / MOSS_PROJECT_KEY are not set."
                if misconfigured
                else f"RETRIEVAL_BACKEND is {settings.retrieval_backend!r}, not 'moss'."
            ),
        )

    outcome = _retrieve_faiss(query, k, trace)
    outcome.warnings = warnings + outcome.warnings
    outcome.moss_record = moss_record
    return outcome


async def _retrieve_moss(
    query: str, k: int, trace: LatencyTrace | None
) -> tuple[RetrievalOutcome | None, MossStageRecord]:
    """Search Moss and normalise its hits.

    Returns ``(None, record)`` when Moss could not serve the query, so the
    caller can fall back while still recording exactly what Moss did.
    """
    retriever = get_moss_retriever()

    if trace is not None:
        with trace.span(RETRIEVAL):
            result, record = await retriever.search_recorded(
                query, stage=MossStage.PRIMARY_RETRIEVAL, top_k=k
            )
    else:
        result, record = await retriever.search_recorded(
            query, stage=MossStage.PRIMARY_RETRIEVAL, top_k=k
        )

    if result is None or not result.hits:
        return None, record

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

    return (
        RetrievalOutcome(
            chunks=chunks,
            backend=RetrievalBackend.MOSS,
            engine_ms=result.time_taken_ms,
            moss_record=record,
        ),
        record,
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
