"""Moss to FAISS fallback tests.

These protect the project's central anti-fabrication guarantee: a trace must
never be labelled ``moss`` unless Moss actually served it. Both failure modes
are covered — Moss unconfigured, and Moss configured but erroring — because the
dashboard attributes retrieval quality to whichever engine it names.
"""

from __future__ import annotations

import pytest

import app.retrieval.retriever as retriever_module
from app.config.settings import Settings
from app.integrations.moss.client import MossRetriever, MossUnavailable
from app.retrieval.retriever import retrieve
from app.schemas.common import RetrievalBackend
from app.tracing.timer import LatencyTrace


@pytest.fixture
def restore_retriever():
    original = retriever_module.get_moss_retriever
    yield
    retriever_module.get_moss_retriever = original


async def test_unconfigured_moss_falls_back_and_is_labelled_faiss():
    """With no credentials, retrieval still works but is never called Moss."""
    settings = Settings(
        retrieval_backend="moss", moss_project_id="", moss_project_key=""
    )
    outcome = await retrieve("What is the refund period?", trace=LatencyTrace(), settings=settings)

    assert outcome.backend is not RetrievalBackend.MOSS
    assert any("Moss is not configured" in warning for warning in outcome.warnings)


async def test_failing_moss_falls_back_and_surfaces_the_real_error(restore_retriever):
    """A Moss outage degrades to FAISS with the actual error reported."""

    class FailingMoss(MossRetriever):
        @property
        def configured(self) -> bool:
            return True

        async def search(self, query, top_k=None):
            raise MossUnavailable("simulated Moss outage: connection reset")

    settings = Settings(
        retrieval_backend="moss", moss_project_id="id", moss_project_key="key"
    )
    retriever_module.get_moss_retriever = lambda: FailingMoss(settings)

    outcome = await retrieve("What is the refund period?", trace=LatencyTrace(), settings=settings)

    assert outcome.backend is not RetrievalBackend.MOSS, (
        "a failed Moss query must never be attributed to Moss"
    )
    assert any("Moss retrieval failed" in warning for warning in outcome.warnings)
    assert any("connection reset" in warning for warning in outcome.warnings), (
        "the underlying cause should reach the operator, not be swallowed"
    )


async def test_failed_moss_reports_no_engine_timing(restore_retriever):
    """``engine_ms`` is Moss's own measurement; it must stay None if Moss failed."""

    class FailingMoss(MossRetriever):
        @property
        def configured(self) -> bool:
            return True

        async def search(self, query, top_k=None):
            raise MossUnavailable("boom")

    settings = Settings(
        retrieval_backend="moss", moss_project_id="id", moss_project_key="key"
    )
    retriever_module.get_moss_retriever = lambda: FailingMoss(settings)

    outcome = await retrieve("refund", trace=LatencyTrace(), settings=settings)
    assert outcome.engine_ms is None


async def test_faiss_backend_setting_skips_moss_entirely(restore_retriever):
    """RETRIEVAL_BACKEND=faiss must not touch Moss at all."""
    called = False

    class ShouldNotBeCalled(MossRetriever):
        @property
        def configured(self) -> bool:
            return True

        async def search(self, query, top_k=None):
            nonlocal called
            called = True
            raise AssertionError("Moss must not be queried when backend is faiss")

    settings = Settings(
        retrieval_backend="faiss", moss_project_id="id", moss_project_key="key"
    )
    retriever_module.get_moss_retriever = lambda: ShouldNotBeCalled(settings)

    outcome = await retrieve("refund", trace=LatencyTrace(), settings=settings)
    assert called is False
    assert outcome.backend is not RetrievalBackend.MOSS
