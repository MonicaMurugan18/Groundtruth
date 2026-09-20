"""Moss integration adapter.

Moss (https://docs.usemoss.dev/) is an embedded semantic search engine: queries
run inside the process with no round-trip to a vector database. It is the
primary retrieval backend in the Groundtruth architecture, and it reports its
own search duration, which we fold straight into the latency trace.

The API used here was verified against the official
``livekit-examples/moss-hacker-starter`` reference implementation:

    from moss import DocumentInfo, MossClient, QueryOptions

    client = MossClient(project_id, project_key)
    await client.create_index(index_name, documents, model_id)
    await client.load_index(index_name)
    await client.add_docs(index_name, [DocumentInfo(id=..., text=..., metadata=...)])
    result = await client.query(index_name, text, QueryOptions(top_k=5, alpha=0.8))
    # result.docs[].text / .score / .metadata, result.time_taken_ms

Honesty contract
----------------
If credentials are absent this adapter reports ``configured == False`` and every
operation raises :class:`MossNotConfigured`. It never returns synthesised
results, and the orchestrator labels any fallback retrieval as FAISS so the
dashboard cannot attribute FAISS results to Moss.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class MossNotConfigured(RuntimeError):
    """Raised when Moss is used without MOSS_PROJECT_ID / MOSS_PROJECT_KEY."""


class MossUnavailable(RuntimeError):
    """Raised when Moss is configured but the operation failed."""


@dataclass(slots=True)
class MossHit:
    """One search result, normalised out of the SDK's response object."""

    text: str
    score: float | None
    metadata: dict[str, Any]


@dataclass(slots=True)
class MossSearchResult:
    hits: list[MossHit]
    # Moss's own measurement of the search, distinct from our wall-clock span.
    time_taken_ms: float | None
    # Echoed back by the SDK's SearchResult so the trace records what Moss
    # actually received and which index answered, rather than what we assumed.
    index_name: str | None = None
    model_id: str | None = None
    echoed_query: str | None = None


class MossStage(str, Enum):
    """Which pipeline step issued a Moss call."""

    PRIMARY_RETRIEVAL = "primary_retrieval"
    EVIDENCE_VERIFICATION = "evidence_verification"


class MossStatus(str, Enum):
    """Outcome of a single Moss call, recorded verbatim on the trace."""

    SUCCESS = "success"
    EMPTY = "empty"          # Moss answered, but matched nothing
    FAILED = "failed"        # Moss was called and errored
    NOT_CONFIGURED = "not_configured"
    SKIPPED = "skipped"      # deliberately not called


@dataclass(slots=True)
class MossStageRecord:
    """An auditable record of one Moss call.

    Every field is either measured or returned by Moss. Nothing here is
    inferred: when a call fails, ``engine_ms`` stays None rather than being
    filled with our wall-clock time, and ``error`` carries Moss's own message.
    """

    stage: MossStage
    status: MossStatus
    query: str | None = None
    index: str | None = None
    result_count: int = 0
    engine_ms: float | None = None   # Moss self-reported
    wall_ms: float | None = None     # our measurement, including transport
    top_score: float | None = None
    model_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "status": self.status.value,
            "query": self.query,
            "index": self.index,
            "result_count": self.result_count,
            "engine_ms": self.engine_ms,
            "wall_ms": self.wall_ms,
            "top_score": self.top_score,
            "model_id": self.model_id,
            "error": self.error,
        }


class MossRetriever:
    """Thin, dependency-isolating wrapper around the Moss SDK."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Any | None = None
        self._loaded_indexes: set[str] = set()
        self._lock = asyncio.Lock()
        # Circuit breaker. A failing Moss call is not cheap: the SDK retries
        # internally, so an outage costs ~2.5s per attempt, and the pipeline
        # makes two Moss calls per evaluation. Once Moss has failed we stop
        # calling it for a short window - that keeps a quota outage from both
        # burning more quota and adding seconds to every request. The remembered
        # error is still reported, so the trace stays truthful about why.
        self._failed_until: float = 0.0
        self._last_error: str | None = None

    def _circuit_open(self) -> bool:
        return time.monotonic() < self._failed_until

    def _trip_circuit(self, error: str) -> None:
        self._failed_until = time.monotonic() + self._settings.moss_failure_cooldown_s
        self._last_error = error

    def _reset_circuit(self) -> None:
        self._failed_until = 0.0
        self._last_error = None

    # -- Status ----------------------------------------------------------

    @property
    def configured(self) -> bool:
        return self._settings.moss_configured

    @property
    def index_name(self) -> str:
        return self._settings.moss_index_name

    def _require_configured(self) -> None:
        if not self.configured:
            raise MossNotConfigured(
                "Moss is not configured. Set MOSS_PROJECT_ID and MOSS_PROJECT_KEY "
                "in backend/.env to enable Moss retrieval."
            )

    # -- Client ----------------------------------------------------------

    def _get_client(self) -> Any:
        """Construct the SDK client lazily so import cost is not paid at boot."""
        self._require_configured()
        if self._client is None:
            try:
                from moss import MossClient
            except ImportError as exc:  # pragma: no cover - dependency guard
                raise MossUnavailable(
                    "The 'moss' package is not installed. Run: pip install moss"
                ) from exc
            self._client = MossClient(
                self._settings.moss_project_id, self._settings.moss_project_key
            )
            logger.info("Moss client initialised for index %r", self.index_name)
        return self._client

    @staticmethod
    def _to_documents(chunks: list[dict[str, Any]]) -> list[Any]:
        """Convert internal chunk dicts into Moss ``DocumentInfo`` objects.

        Moss requires metadata values to be strings, so every value is coerced.
        """
        from moss import DocumentInfo

        documents = []
        for chunk in chunks:
            metadata = {str(k): str(v) for k, v in (chunk.get("metadata") or {}).items()}
            documents.append(
                DocumentInfo(
                    id=str(chunk["id"]),
                    text=str(chunk["text"]),
                    metadata=metadata,
                )
            )
        return documents

    # -- Indexing --------------------------------------------------------

    async def create_index(self, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        """Create (or replace) the knowledge index from ``chunks``."""
        self._require_configured()
        client = self._get_client()
        documents = self._to_documents(chunks)
        try:
            result = await client.create_index(
                self.index_name, documents, self._settings.moss_model_id
            )
        except Exception as exc:
            raise MossUnavailable(f"Moss create_index failed: {exc}") from exc

        self._loaded_indexes.discard(self.index_name)
        return {
            "job_id": getattr(result, "job_id", None),
            "index_name": getattr(result, "index_name", self.index_name),
            "doc_count": getattr(result, "doc_count", len(documents)),
        }

    async def add_documents(self, chunks: list[dict[str, Any]]) -> int:
        """Append chunks to an existing index and reload it.

        Moss guidance is to reload after a write so new documents are
        immediately queryable.
        """
        self._require_configured()
        client = self._get_client()
        documents = self._to_documents(chunks)
        try:
            await client.add_docs(self.index_name, documents)
        except Exception as exc:
            raise MossUnavailable(f"Moss add_docs failed: {exc}") from exc

        try:
            await client.load_index(self.index_name)
            self._loaded_indexes.add(self.index_name)
        except Exception:
            # Non-fatal: the next query re-attempts the load.
            logger.exception("Failed to reload Moss index after write")
            self._loaded_indexes.discard(self.index_name)
        return len(documents)

    async def ensure_loaded(self) -> None:
        """Preload the index so the first query is fast."""
        self._require_configured()
        if self.index_name in self._loaded_indexes:
            return
        async with self._lock:
            if self.index_name in self._loaded_indexes:
                return
            client = self._get_client()
            try:
                await client.load_index(self.index_name)
            except Exception as exc:
                raise MossUnavailable(
                    f"Moss load_index({self.index_name!r}) failed: {exc}"
                ) from exc
            self._loaded_indexes.add(self.index_name)
            logger.info("Moss index %r loaded", self.index_name)

    # -- Search ----------------------------------------------------------

    async def search(self, query: str, top_k: int | None = None) -> MossSearchResult:
        """Run a semantic search. Raises rather than returning empty on failure."""
        self._require_configured()
        await self.ensure_loaded()
        client = self._get_client()

        from moss import QueryOptions

        options = QueryOptions(
            top_k=top_k or self._settings.moss_top_k,
            alpha=self._settings.moss_alpha,
        )
        try:
            result = await client.query(self.index_name, query, options)
        except Exception as exc:
            raise MossUnavailable(f"Moss query failed: {exc}") from exc

        hits: list[MossHit] = []
        for doc in getattr(result, "docs", None) or []:
            text = (getattr(doc, "text", "") or "").strip()
            if not text:
                continue
            raw_score = getattr(doc, "score", None)
            try:
                score = float(raw_score) if raw_score is not None else None
            except (TypeError, ValueError):
                score = None
            hits.append(
                MossHit(
                    text=text,
                    score=score,
                    metadata=dict(getattr(doc, "metadata", None) or {}),
                )
            )

        raw_time = getattr(result, "time_taken_ms", None)
        try:
            time_taken = float(raw_time) if raw_time is not None else None
        except (TypeError, ValueError):
            time_taken = None

        return MossSearchResult(
            hits=hits,
            time_taken_ms=time_taken,
            # SearchResult echoes these back; recording Moss's own values keeps
            # the trace honest about which index actually answered.
            index_name=getattr(result, "index_name", None),
            model_id=getattr(result, "model_id", None),
            echoed_query=getattr(result, "query", None),
        )

    # -- Instrumented calls used by the pipeline --------------------------

    async def search_recorded(
        self,
        query: str,
        *,
        stage: MossStage,
        top_k: int | None = None,
    ) -> tuple[MossSearchResult | None, MossStageRecord]:
        """Run a search and return it alongside an auditable stage record.

        Never raises. Callers get a record describing exactly what happened, so
        a Moss outage becomes a visible, attributable trace entry instead of an
        exception that has to be re-interpreted further up the stack.
        """
        record = MossStageRecord(
            stage=stage,
            status=MossStatus.SKIPPED,
            query=query,
            index=self.index_name,
        )

        if not self.configured:
            record.status = MossStatus.NOT_CONFIGURED
            record.error = (
                "MOSS_PROJECT_ID / MOSS_PROJECT_KEY are not set."
            )
            return None, record

        if self._circuit_open():
            # Reported as a failure, not a silent skip: Moss genuinely is not
            # serving, and the trace should say so with the original reason.
            record.status = MossStatus.FAILED
            record.error = (
                f"Skipped: Moss failed recently and is in a "
                f"{self._settings.moss_failure_cooldown_s:.0f}s cooldown to avoid "
                f"burning quota. Last error: {self._last_error}"
            )
            return None, record

        started = time.perf_counter()
        try:
            result = await self.search(query, top_k=top_k)
        except (MossNotConfigured, MossUnavailable) as exc:
            record.wall_ms = round((time.perf_counter() - started) * 1000, 2)
            record.status = (
                MossStatus.NOT_CONFIGURED
                if isinstance(exc, MossNotConfigured)
                else MossStatus.FAILED
            )
            # Moss's own message, preserved verbatim for the trace and the UI.
            record.error = str(exc)
            if record.status is MossStatus.FAILED:
                self._trip_circuit(record.error)
            # engine_ms deliberately stays None: Moss reported no timing.
            return None, record

        record.wall_ms = round((time.perf_counter() - started) * 1000, 2)
        record.engine_ms = result.time_taken_ms
        record.result_count = len(result.hits)
        record.index = result.index_name or self.index_name
        record.model_id = result.model_id
        scores = [hit.score for hit in result.hits if hit.score is not None]
        record.top_score = max(scores) if scores else None
        record.status = MossStatus.SUCCESS if result.hits else MossStatus.EMPTY
        self._reset_circuit()  # Moss answered; clear any previous outage state
        return result, record


_retriever: MossRetriever | None = None


def get_moss_retriever() -> MossRetriever:
    """Return the process-wide Moss adapter."""
    global _retriever
    if _retriever is None:
        _retriever = MossRetriever()
    return _retriever
