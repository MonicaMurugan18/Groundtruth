"""Moss integration tests.

Moss is the primary retrieval backend and the evidence-verification stage, so
these tests pin the behaviour that matters for trustworthiness:

* a Moss-served query is labelled Moss, with Moss's own timing
* a failed Moss call is never labelled Moss and never invents timing
* the verbatim Moss error survives to the trace and the UI

The Moss SDK is stubbed rather than called. That is deliberate and not a
weakening: the live API was verified separately (a real index was created and
queried), while these tests must run deterministically and must not consume
quota. The stub mirrors the SDK's real response shape - ``docs`` with
``text``/``score``/``metadata``, plus ``time_taken_ms``, ``index_name`` and
``model_id`` - which is exactly the surface the adapter reads.
"""

from __future__ import annotations

import pytest

import app.retrieval.retriever as retriever_module
from app.config.settings import Settings
from app.integrations.moss.client import (
    MossRetriever,
    MossStage,
    MossStageRecord,
    MossStatus,
    MossUnavailable,
)
from app.retrieval.evidence import verify_with_moss
from app.retrieval.retriever import retrieve
from app.schemas.common import RetrievalBackend
from app.tracing.timer import LatencyTrace

MOSS_SETTINGS = Settings(
    retrieval_backend="moss",
    moss_project_id="test-id",
    moss_project_key="test-key",
    moss_index_name="test-index",
)


# --------------------------------------------------------------------------
# Stubs mirroring the real SDK response shape
# --------------------------------------------------------------------------


class _StubDoc:
    def __init__(self, text, score, metadata=None):
        self.text = text
        self.score = score
        self.metadata = metadata or {}


class _StubSearchResult:
    def __init__(self, docs, time_taken_ms=2.0, index_name="test-index", model_id="moss-minilm"):
        self.docs = docs
        self.time_taken_ms = time_taken_ms
        self.index_name = index_name
        self.model_id = model_id
        self.query = "echoed"


class _StubRetriever(MossRetriever):
    """A MossRetriever whose `search` is replaced, leaving recording intact."""

    def __init__(self, result=None, error=None, settings=MOSS_SETTINGS):
        super().__init__(settings)
        self._result = result
        self._error = error
        self.calls: list[str] = []

    @property
    def configured(self) -> bool:
        return True

    async def search(self, query, top_k=None):
        self.calls.append(query)
        if self._error is not None:
            raise self._error
        from app.integrations.moss.client import MossHit, MossSearchResult

        docs = self._result or []
        return MossSearchResult(
            hits=[MossHit(text=d.text, score=d.score, metadata=d.metadata) for d in docs],
            time_taken_ms=2.0,
            index_name="test-index",
            model_id="moss-minilm",
        )


@pytest.fixture
def restore_retriever():
    original = retriever_module.get_moss_retriever
    yield
    retriever_module.get_moss_retriever = original


# --------------------------------------------------------------------------
# 1. Moss as primary retrieval
# --------------------------------------------------------------------------


async def test_moss_serves_primary_retrieval_and_is_labelled_moss(restore_retriever):
    stub = _StubRetriever([_StubDoc("The refund period is 7 days.", 0.93, {"source": "policy.txt"})])
    retriever_module.get_moss_retriever = lambda: stub

    outcome = await retrieve(
        "What is the refund period?", trace=LatencyTrace(), settings=MOSS_SETTINGS
    )

    assert outcome.backend is RetrievalBackend.MOSS
    assert len(outcome.chunks) == 1
    assert stub.calls == ["What is the refund period?"], "exactly one Moss call"


async def test_moss_records_its_own_engine_timing(restore_retriever):
    """``engine_ms`` must be Moss's number, not our wall clock."""
    retriever_module.get_moss_retriever = lambda: _StubRetriever([_StubDoc("x", 0.9)])

    outcome = await retrieve("q", trace=LatencyTrace(), settings=MOSS_SETTINGS)

    assert outcome.engine_ms == 2.0
    assert outcome.moss_record.engine_ms == 2.0
    # Our own measurement is recorded separately, never conflated.
    assert outcome.moss_record.wall_ms is not None


async def test_moss_result_parsing_preserves_scores_and_metadata(restore_retriever):
    retriever_module.get_moss_retriever = lambda: _StubRetriever(
        [_StubDoc("Refunds within 7 days.", 0.88, {"source": "policy.txt", "doc_id": "d1"})]
    )

    outcome = await retrieve("refund", trace=LatencyTrace(), settings=MOSS_SETTINGS)
    chunk = outcome.chunks[0]

    assert chunk.source == "policy.txt"
    assert chunk.chunk_id == "d1"
    # Moss's own score is preserved alongside the comparable cosine.
    assert chunk.metadata["moss_score"] == 0.88


# --------------------------------------------------------------------------
# 2. Stage recording
# --------------------------------------------------------------------------


async def test_successful_stage_record_captures_moss_fields(restore_retriever):
    retriever_module.get_moss_retriever = lambda: _StubRetriever(
        [_StubDoc("a", 0.9), _StubDoc("b", 0.5)]
    )

    outcome = await retrieve("q", trace=LatencyTrace(), settings=MOSS_SETTINGS)
    record = outcome.moss_record

    assert record.stage is MossStage.PRIMARY_RETRIEVAL
    assert record.status is MossStatus.SUCCESS
    assert record.result_count == 2
    assert record.index == "test-index"
    assert record.model_id == "moss-minilm"
    assert record.top_score == 0.9
    assert record.error is None


async def test_stage_record_is_json_serialisable_for_the_trace():
    record = MossStageRecord(
        stage=MossStage.PRIMARY_RETRIEVAL, status=MossStatus.SUCCESS, result_count=2
    )
    payload = record.to_dict()
    assert payload["stage"] == "primary_retrieval"
    assert payload["status"] == "success"
    assert set(payload) >= {
        "stage", "status", "query", "index", "result_count",
        "engine_ms", "wall_ms", "top_score", "error",
    }


# --------------------------------------------------------------------------
# 3. Failure -> FAISS fallback, reported honestly
# --------------------------------------------------------------------------


async def test_usage_limit_error_falls_back_and_preserves_the_real_message(restore_retriever):
    """The exact failure seen in production: Moss credits exhausted."""
    real_error = (
        "Moss query failed: Cloud error: HTTP 429 Too Many Requests: "
        '{"error":"USAGE_LIMIT_EXCEEDED","message":"credit_exhausted"}'
    )
    retriever_module.get_moss_retriever = lambda: _StubRetriever(
        error=MossUnavailable(real_error)
    )

    outcome = await retrieve("q", trace=LatencyTrace(), settings=MOSS_SETTINGS)

    assert outcome.backend is not RetrievalBackend.MOSS, "a failed call is never labelled Moss"
    assert outcome.moss_record.status is MossStatus.FAILED
    assert "USAGE_LIMIT_EXCEEDED" in outcome.moss_record.error
    assert any("USAGE_LIMIT_EXCEEDED" in w for w in outcome.warnings)


async def test_failed_moss_never_fabricates_engine_timing(restore_retriever):
    retriever_module.get_moss_retriever = lambda: _StubRetriever(
        error=MossUnavailable("boom")
    )

    outcome = await retrieve("q", trace=LatencyTrace(), settings=MOSS_SETTINGS)

    assert outcome.engine_ms is None
    assert outcome.moss_record.engine_ms is None, "Moss reported no timing; none may be invented"


async def test_moss_returning_no_matches_falls_back_without_calling_it_a_failure(restore_retriever):
    retriever_module.get_moss_retriever = lambda: _StubRetriever([])

    outcome = await retrieve("q", trace=LatencyTrace(), settings=MOSS_SETTINGS)

    assert outcome.moss_record.status is MossStatus.EMPTY
    assert outcome.backend is not RetrievalBackend.MOSS


async def test_failure_triggers_exactly_one_moss_call(restore_retriever):
    """A failing Moss must not be retried in a loop and burn quota."""
    stub = _StubRetriever(error=MossUnavailable("credit_exhausted"))
    retriever_module.get_moss_retriever = lambda: stub

    await retrieve("q", trace=LatencyTrace(), settings=MOSS_SETTINGS)

    assert len(stub.calls) == 1


async def test_unconfigured_moss_is_recorded_as_not_configured():
    settings = Settings(retrieval_backend="moss", moss_project_id="", moss_project_key="")
    outcome = await retrieve("q", trace=LatencyTrace(), settings=settings)

    assert outcome.backend is not RetrievalBackend.MOSS
    assert outcome.moss_record.status is MossStatus.NOT_CONFIGURED


# --------------------------------------------------------------------------
# 4. Evidence verification (second Moss stage)
# --------------------------------------------------------------------------


async def test_evidence_stage_queries_moss_with_the_answer(monkeypatch):
    """The evidence stage asks about the *answer*, not the original question."""
    stub = _StubRetriever([_StubDoc("The refund period is 7 days.", 0.95)])
    monkeypatch.setattr("app.retrieval.evidence.get_moss_retriever", lambda: stub)

    evidence, record = await verify_with_moss(
        "The refund period is 7 days.", settings=MOSS_SETTINGS
    )

    assert stub.calls == ["The refund period is 7 days."]
    assert record.stage is MossStage.EVIDENCE_VERIFICATION
    assert evidence.status == "success"
    assert evidence.match_count == 1
    assert evidence.top_score == 0.95
    assert evidence.engine_ms == 2.0


async def test_evidence_stage_never_claims_to_prove_truth(monkeypatch):
    monkeypatch.setattr(
        "app.retrieval.evidence.get_moss_retriever",
        lambda: _StubRetriever([_StubDoc("x", 0.9)]),
    )
    evidence, _ = await verify_with_moss("some answer", settings=MOSS_SETTINGS)
    assert "does not establish that the answer is true" in evidence.reason


async def test_evidence_stage_reports_no_corroboration_without_calling_it_false(monkeypatch):
    monkeypatch.setattr(
        "app.retrieval.evidence.get_moss_retriever", lambda: _StubRetriever([])
    )
    evidence, _ = await verify_with_moss("an unsupported claim", settings=MOSS_SETTINGS)

    assert evidence.status == "empty"
    assert evidence.match_count == 0
    assert "not proof the answer is wrong" in evidence.reason


async def test_evidence_stage_survives_a_moss_outage(monkeypatch):
    monkeypatch.setattr(
        "app.retrieval.evidence.get_moss_retriever",
        lambda: _StubRetriever(error=MossUnavailable("credit_exhausted")),
    )
    evidence, record = await verify_with_moss("answer", settings=MOSS_SETTINGS)

    assert record.status is MossStatus.FAILED
    assert "credit_exhausted" in record.error
    assert evidence.engine_ms is None


async def test_evidence_stage_is_skipped_when_disabled():
    settings = MOSS_SETTINGS.model_copy(update={"moss_evidence_enabled": False})
    evidence, record = await verify_with_moss("answer", settings=settings)

    assert record.status is MossStatus.SKIPPED
    assert evidence.status == "skipped"


async def test_evidence_stage_skipped_for_an_empty_answer():
    evidence, record = await verify_with_moss("   ", settings=MOSS_SETTINGS)
    assert record.status is MossStatus.SKIPPED
    assert "nothing to corroborate" in record.error


# --------------------------------------------------------------------------
# 5. Circuit breaker: an outage must not cost time on every later request
# --------------------------------------------------------------------------


async def test_circuit_breaker_stops_calling_a_failing_moss():
    """After a failure, Moss is not called again during the cooldown.

    A failing Moss call costs seconds (the SDK retries internally) and the
    pipeline makes two per evaluation, so without this an outage would tax
    every request and keep consuming quota.
    """
    stub = _StubRetriever(error=MossUnavailable("credit_exhausted"))

    first, record1 = await stub.search_recorded("q1", stage=MossStage.PRIMARY_RETRIEVAL)
    assert first is None
    assert record1.status is MossStatus.FAILED
    assert len(stub.calls) == 1

    second, record2 = await stub.search_recorded("q2", stage=MossStage.EVIDENCE_VERIFICATION)
    assert second is None
    assert len(stub.calls) == 1, "Moss must not be called again during cooldown"
    # Still reported as a failure, carrying the original cause.
    assert record2.status is MossStatus.FAILED
    assert "credit_exhausted" in record2.error
    assert "cooldown" in record2.error


async def test_circuit_breaker_clears_once_moss_answers():
    stub = _StubRetriever([_StubDoc("ok", 0.9)])
    stub._trip_circuit("earlier outage")
    stub._reset_circuit()  # a later success clears it

    result, record = await stub.search_recorded("q", stage=MossStage.PRIMARY_RETRIEVAL)
    assert result is not None
    assert record.status is MossStatus.SUCCESS


async def test_cooldown_does_not_apply_when_moss_is_healthy():
    stub = _StubRetriever([_StubDoc("a", 0.9)])
    for i in range(3):
        result, record = await stub.search_recorded(f"q{i}", stage=MossStage.PRIMARY_RETRIEVAL)
        assert record.status is MossStatus.SUCCESS
    assert len(stub.calls) == 3, "healthy Moss is called every time"
