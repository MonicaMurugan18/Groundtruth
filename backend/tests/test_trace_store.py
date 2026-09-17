"""Trace persistence round-trip tests.

The stored trace is what an engineer opens days later to understand a failure,
so it has to survive the round-trip with its meaning intact. These tests run
against a real (in-memory) SQLite database rather than mocks, because the thing
being checked is the mapping between the ORM and the API schema.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.trace import EvaluationTrace  # noqa: F401  (registers tables)
from app.schemas.common import (
    ContextValidationStatus,
    GuardrailStatus,
    MetricStatus,
    ReliabilityStatus,
    RetrievalBackend,
    SourceChannel,
)
from app.schemas.evaluation import (
    ContextValidation,
    EvaluationResponse,
    FactualVerification,
    GuardrailResult,
    LatencyBreakdown,
    MetricScore,
    RetrievedChunk,
)
from app.services import trace_store


@pytest.fixture
async def session():
    """A fresh in-memory database per test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


def _response(**overrides) -> EvaluationResponse:
    payload = {
        "evaluation_id": "test-eval-1",
        "created_at": datetime.now(timezone.utc),
        "channel": SourceChannel.TEXT,
        "query": "What is the refund period?",
        "contexts": [
            RetrievedChunk(
                text="Refunds are available within 7 days.",
                score=0.61,
                source="policies.txt",
                chunk_id="abc123",
                metadata={"doc_id": "policies.txt"},
            )
        ],
        "answer": "Refunds are available within 7 days.",
        "faithfulness": MetricScore(value=0.95, status=MetricStatus.OK),
        "answer_relevance": MetricScore(value=0.9, status=MetricStatus.OK),
        "context_precision": MetricScore(value=0.8, status=MetricStatus.OK),
        "context_validation": ContextValidation(
            status=ContextValidationStatus.RELEVANT,
            reason="Strong match.",
            chunks_retrieved=1,
            max_similarity=0.61,
            mean_similarity=0.61,
        ),
        "guardrail": GuardrailResult(status=GuardrailStatus.PASS, reason="No violation."),
        "factual_verification": FactualVerification(
            status=MetricStatus.NOT_APPLICABLE, reason="No reference supplied."
        ),
        "status": ReliabilityStatus.RELIABLE,
        "explanation": "Everything is supported.",
        "supported": True,
        "retrieval_backend": RetrievalBackend.FAISS,
        "latency": LatencyBreakdown(retrieval_ms=12.5, llm_ms=840.0, total_ms=900.0),
        "warnings": [],
    }
    payload.update(overrides)
    return EvaluationResponse(**payload)


async def test_round_trip_preserves_scores_and_verdict(session):
    original = _response()
    await trace_store.save(session, original)

    row = await trace_store.get_trace(session, "test-eval-1")
    assert row is not None
    restored = trace_store.to_response(row)

    assert restored.status is ReliabilityStatus.RELIABLE
    assert restored.faithfulness.value == pytest.approx(0.95)
    assert restored.supported is True
    assert restored.retrieval_backend is RetrievalBackend.FAISS
    assert restored.explanation == original.explanation


async def test_round_trip_preserves_retrieved_context(session):
    """The chunks are the evidence; losing them makes the trace unusable."""
    await trace_store.save(session, _response())
    row = await trace_store.get_trace(session, "test-eval-1")
    restored = trace_store.to_response(row)

    assert len(restored.contexts) == 1
    chunk = restored.contexts[0]
    assert chunk.text == "Refunds are available within 7 days."
    assert chunk.source == "policies.txt"
    assert chunk.score == pytest.approx(0.61)


async def test_round_trip_preserves_why_a_metric_was_not_computed(session):
    """An uncomputed metric must keep its reason, not degrade to a bare status.

    Without this the trace view can only say "not computed", while the live
    response explained why — and the trace view is what gets read later.
    """
    reason = "No answer was generated (the LLM is unavailable), so there is nothing to score."
    await trace_store.save(
        session,
        _response(
            faithfulness=MetricScore(status=MetricStatus.NOT_APPLICABLE, detail=reason),
        ),
    )

    row = await trace_store.get_trace(session, "test-eval-1")
    restored = trace_store.to_response(row)

    assert restored.faithfulness.value is None
    assert restored.faithfulness.status is MetricStatus.NOT_APPLICABLE
    assert restored.faithfulness.detail == reason


async def test_null_score_is_stored_as_null_not_zero(session):
    """The core honesty guarantee, enforced at the storage layer."""
    await trace_store.save(
        session,
        _response(faithfulness=MetricScore(status=MetricStatus.UNAVAILABLE, detail="no key")),
    )

    row = await trace_store.get_trace(session, "test-eval-1")
    assert row.faithfulness_score is None, "must be NULL, never 0.0"
    assert row.faithfulness_status == "unavailable"


async def test_latency_detail_survives_round_trip(session):
    await trace_store.save(session, _response())
    row = await trace_store.get_trace(session, "test-eval-1")
    restored = trace_store.to_response(row)

    assert restored.latency.total_ms == pytest.approx(900.0)
    assert restored.latency.retrieval_ms == pytest.approx(12.5)
    assert restored.latency.llm_ms == pytest.approx(840.0)


async def test_stats_ignore_null_scores_rather_than_averaging_them_as_zero(session):
    """One scored and one unscored trace must average to the scored value.

    Treating NULL as 0.0 would report 47.5% here instead of 95%, which would
    make a healthy agent look broken purely because a metric was unavailable.
    """
    await trace_store.save(session, _response())
    await trace_store.save(
        session,
        _response(
            evaluation_id="test-eval-2",
            faithfulness=MetricScore(status=MetricStatus.UNAVAILABLE, detail="no key"),
        ),
    )

    stats = await trace_store.get_stats(session)
    assert stats.total_evaluations == 2
    assert stats.avg_faithfulness == pytest.approx(0.95)


async def test_stats_count_guardrail_violations(session):
    await trace_store.save(session, _response())
    await trace_store.save(
        session,
        _response(
            evaluation_id="test-eval-3",
            guardrail=GuardrailResult(
                status=GuardrailStatus.BLOCK, reason="Unsafe request."
            ),
            status=ReliabilityStatus.FAILED,
        ),
    )

    stats = await trace_store.get_stats(session)
    assert stats.guardrail_violations == 1
    assert stats.failed_count == 1
    assert stats.reliable_count == 1


async def test_history_filters_by_status(session):
    await trace_store.save(session, _response())
    await trace_store.save(
        session,
        _response(evaluation_id="test-eval-4", status=ReliabilityStatus.FAILED),
    )

    failed, total = await trace_store.list_traces(session, status="failed")
    assert total == 1
    assert failed[0].evaluation_id == "test-eval-4"
