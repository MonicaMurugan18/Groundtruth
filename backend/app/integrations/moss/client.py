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
from dataclasses import dataclass
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


class MossRetriever:
    """Thin, dependency-isolating wrapper around the Moss SDK."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Any | None = None
        self._loaded_indexes: set[str] = set()
        self._lock = asyncio.Lock()

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

        return MossSearchResult(hits=hits, time_taken_ms=time_taken)


_retriever: MossRetriever | None = None


def get_moss_retriever() -> MossRetriever:
    """Return the process-wide Moss adapter."""
    global _retriever
    if _retriever is None:
        _retriever = MossRetriever()
    return _retriever
