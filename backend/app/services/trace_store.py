"""Persistence and aggregation for evaluation traces.

Converts between the API schema and the ORM rows, and computes the dashboard
aggregates in SQL rather than in Python so the numbers stay correct as the trace
table grows.

Averages deliberately ignore NULL scores. A metric that could not be computed
must not drag an average toward zero - ``AVG`` skipping NULLs is exactly the
behaviour we want, and the dashboard shows the sample size alongside.
"""

from __future__ import annotations

import logging

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trace import EvaluationTrace, RetrievedContext
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
    DashboardStats,
    EvaluationResponse,
    FactualVerification,
    GuardrailResult,
    LatencyBreakdown,
    MetricScore,
    MossEvidence,
    MossStageInfo,
    RetrievedChunk,
    TraceSummary,
)


logger = logging.getLogger(__name__)


def _primary_moss_status(response: EvaluationResponse) -> str:
    """Status of the primary-retrieval Moss call, or 'skipped' if there was none."""
    for stage in response.moss_stages:
        if stage.stage == "primary_retrieval":
            return stage.status
    return "skipped"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


async def save(
    db: AsyncSession,
    response: EvaluationResponse,
    *,
    reference_answer: str | None = None,
) -> EvaluationTrace:
    """Persist one complete evaluation."""
    latency = response.latency.model_dump()

    trace = EvaluationTrace(
        evaluation_id=response.evaluation_id,
        created_at=response.created_at,
        user_query=response.query,
        agent_answer=response.answer,
        reference_answer=reference_answer,
        channel=response.channel.value,
        retrieval_backend=response.retrieval_backend.value,
        moss_status=_primary_moss_status(response),
        moss_stages=[stage.model_dump() for stage in response.moss_stages],
        moss_evidence=(
            response.moss_evidence.model_dump() if response.moss_evidence else {}
        ),
        faithfulness_score=response.faithfulness.value,
        faithfulness_status=response.faithfulness.status.value,
        relevance_score=response.answer_relevance.value,
        relevance_status=response.answer_relevance.status.value,
        retrieval_score=response.context_precision.value,
        retrieval_status=response.context_precision.status.value,
        metric_details={
            "faithfulness": response.faithfulness.detail,
            "answer_relevance": response.answer_relevance.detail,
            "context_precision": response.context_precision.detail,
        },
        context_status=response.context_validation.status.value,
        context_reason=response.context_validation.reason,
        chunks_retrieved=response.context_validation.chunks_retrieved,
        max_similarity=response.context_validation.max_similarity,
        mean_similarity=response.context_validation.mean_similarity,
        guardrail_status=response.guardrail.status.value,
        guardrail_reason=response.guardrail.reason,
        guardrail_triggered=list(response.guardrail.triggered),
        factual_status=response.factual_verification.status.value,
        factual_correct=response.factual_verification.correct,
        factual_score=response.factual_verification.score,
        factual_reason=response.factual_verification.reason,
        retrieval_ms=latency.get("retrieval_ms"),
        llm_ms=latency.get("llm_ms"),
        guardrail_ms=latency.get("guardrail_ms"),
        evaluation_ms=latency.get("evaluation_ms"),
        context_validation_ms=latency.get("context_validation_ms"),
        total_ms=latency.get("total_ms"),
        latency_detail=latency,
        reliability_status=response.status.value,
        supported=response.supported,
        explanation=response.explanation,
        warnings=list(response.warnings),
    )

    for rank, chunk in enumerate(response.contexts):
        trace.contexts.append(
            RetrievedContext(
                trace_id=trace.evaluation_id,
                rank=rank,
                text=chunk.text,
                score=chunk.score,
                source=chunk.source,
                chunk_id=chunk.chunk_id,
                doc_metadata=chunk.metadata,
            )
        )

    db.add(trace)
    await db.commit()
    return trace


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def get_trace(db: AsyncSession, evaluation_id: str) -> EvaluationTrace | None:
    result = await db.execute(
        select(EvaluationTrace).where(EvaluationTrace.evaluation_id == evaluation_id)
    )
    return result.scalar_one_or_none()


def _filtered(
    statement: Select,
    *,
    status: str | None,
    channel: str | None,
) -> Select:
    if status:
        statement = statement.where(EvaluationTrace.reliability_status == status)
    if channel:
        statement = statement.where(EvaluationTrace.channel == channel)
    return statement


async def list_traces(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    channel: str | None = None,
) -> tuple[list[TraceSummary], int]:
    """Return a page of history rows plus the total matching count."""
    statement = _filtered(select(EvaluationTrace), status=status, channel=channel)
    statement = statement.order_by(EvaluationTrace.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(statement)).scalars().all()

    count_statement = _filtered(
        select(func.count(EvaluationTrace.evaluation_id)), status=status, channel=channel
    )
    total = (await db.execute(count_statement)).scalar_one()

    return [_to_summary(row) for row in rows], int(total)


async def get_stats(db: AsyncSession, *, recent_limit: int = 10) -> DashboardStats:
    """Compute the dashboard aggregates."""
    totals = (
        await db.execute(
            select(
                func.count(EvaluationTrace.evaluation_id),
                func.avg(EvaluationTrace.faithfulness_score),
                func.avg(EvaluationTrace.relevance_score),
                func.avg(EvaluationTrace.retrieval_score),
                func.avg(EvaluationTrace.total_ms),
            )
        )
    ).one()

    total, avg_faith, avg_rel, avg_ctx, avg_latency = totals

    status_rows = (
        await db.execute(
            select(EvaluationTrace.reliability_status, func.count())
            .group_by(EvaluationTrace.reliability_status)
        )
    ).all()
    by_status = {status: int(count) for status, count in status_rows}

    guardrail_violations = int(
        (
            await db.execute(
                select(func.count(EvaluationTrace.evaluation_id)).where(
                    EvaluationTrace.guardrail_status.in_(
                        [GuardrailStatus.BLOCK.value, GuardrailStatus.REVIEW.value]
                    )
                )
            )
        ).scalar_one()
    )

    voice_count = int(
        (
            await db.execute(
                select(func.count(EvaluationTrace.evaluation_id)).where(
                    EvaluationTrace.channel == SourceChannel.VOICE.value
                )
            )
        ).scalar_one()
    )

    recent_rows = (
        await db.execute(
            select(EvaluationTrace)
            .order_by(EvaluationTrace.created_at.desc())
            .limit(recent_limit)
        )
    ).scalars().all()

    return DashboardStats(
        total_evaluations=int(total or 0),
        reliable_count=by_status.get(ReliabilityStatus.RELIABLE.value, 0),
        needs_review_count=by_status.get(ReliabilityStatus.NEEDS_REVIEW.value, 0),
        failed_count=by_status.get(ReliabilityStatus.FAILED.value, 0),
        guardrail_violations=guardrail_violations,
        avg_faithfulness=_round(avg_faith),
        avg_relevance=_round(avg_rel),
        avg_context_precision=_round(avg_ctx),
        avg_latency_ms=_round(avg_latency, 2),
        voice_evaluations=voice_count,
        recent=[_to_summary(row) for row in recent_rows],
    )


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def _to_summary(row: EvaluationTrace) -> TraceSummary:
    return TraceSummary(
        evaluation_id=row.evaluation_id,
        created_at=row.created_at,
        query=row.user_query,
        status=ReliabilityStatus(row.reliability_status),
        channel=SourceChannel(row.channel),
        faithfulness=row.faithfulness_score,
        answer_relevance=row.relevance_score,
        guardrail_status=GuardrailStatus(row.guardrail_status),
        total_ms=row.total_ms,
    )


def to_response(row: EvaluationTrace) -> EvaluationResponse:
    """Rebuild the full API response from a stored trace."""
    details = row.metric_details or {}
    return EvaluationResponse(
        evaluation_id=row.evaluation_id,
        created_at=row.created_at,
        channel=SourceChannel(row.channel),
        query=row.user_query,
        contexts=[
            RetrievedChunk(
                text=context.text,
                score=context.score,
                source=context.source,
                chunk_id=context.chunk_id,
                metadata=context.doc_metadata or {},
            )
            for context in row.contexts
        ],
        answer=row.agent_answer,
        faithfulness=MetricScore(
            value=row.faithfulness_score,
            status=MetricStatus(row.faithfulness_status),
            detail=details.get("faithfulness"),
        ),
        answer_relevance=MetricScore(
            value=row.relevance_score,
            status=MetricStatus(row.relevance_status),
            detail=details.get("answer_relevance"),
        ),
        context_precision=MetricScore(
            value=row.retrieval_score,
            status=MetricStatus(row.retrieval_status),
            detail=details.get("context_precision"),
        ),
        context_validation=ContextValidation(
            status=ContextValidationStatus(row.context_status),
            reason=row.context_reason,
            chunks_retrieved=row.chunks_retrieved,
            max_similarity=row.max_similarity,
            mean_similarity=row.mean_similarity,
        ),
        guardrail=GuardrailResult(
            status=GuardrailStatus(row.guardrail_status),
            reason=row.guardrail_reason,
            triggered=list(row.guardrail_triggered or []),
        ),
        factual_verification=FactualVerification(
            status=MetricStatus(row.factual_status),
            correct=row.factual_correct,
            score=row.factual_score,
            reason=row.factual_reason,
        ),
        status=ReliabilityStatus(row.reliability_status),
        explanation=row.explanation,
        supported=row.supported,
        retrieval_backend=RetrievalBackend(row.retrieval_backend),
        moss_stages=[MossStageInfo(**s) for s in (row.moss_stages or [])],
        moss_evidence=(MossEvidence(**row.moss_evidence) if row.moss_evidence else None),
        latency=LatencyBreakdown(**(row.latency_detail or {"total_ms": row.total_ms or 0.0})),
        warnings=list(row.warnings or []),
    )


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)
