"""The Groundtruth pipeline.

Stage order, and why it is this order:

1. **Input guardrail** - before retrieval, so an unsafe query never touches the
   corpus or the LLM. A BLOCK here short-circuits: no retrieval, no generation.
2. **Retrieval** - Moss first, FAISS as fallback, with the serving backend
   recorded on the trace.
3. **Context validation** - judges retrieval on its own, before the answer
   exists, so a retrieval failure is not misattributed to the generator.
4. **Generation** - grounded answer from the retrieved passages only.
5. **Output guardrail** - before the answer is returned to the user.
6. **Evaluation** - RAGAS faithfulness / relevance / context precision, plus
   ground-truth comparison when a reference answer was supplied.
7. **Reliability gate** - deterministic combination of every signal.
8. **Persistence** - the full trace is written to PostgreSQL.

Every stage is timed with a real clock. A stage that cannot run is recorded as
unavailable; nothing in this pipeline substitutes an invented score.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.evaluation import ragas_eval
from app.evaluation.context_validation import validate_context
from app.evaluation.factuality import verify_against_reference
from app.evaluation.reliability import decide
from app.guardrails.engine import get_guardrail_engine
from app.retrieval.evidence import verify_with_moss
from app.retrieval.retriever import retrieve
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
    LatencyBreakdown,
    MetricScore,
    MossStageInfo,
    RetrievedChunk,
)
from app.services import trace_store
from app.services.generation import generate_answer
from app.tracing.timer import (
    CONTEXT_VALIDATION,
    EVALUATION,
    MOSS_EVIDENCE,
    LatencyTrace,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineInput:
    query: str
    top_k: int | None = None
    channel: SourceChannel = SourceChannel.TEXT
    reference_answer: str | None = None


async def run_pipeline(
    request: PipelineInput,
    *,
    db: AsyncSession | None = None,
    settings: Settings | None = None,
) -> EvaluationResponse:
    """Run the full retrieve -> generate -> evaluate cycle for one query."""
    settings = settings or get_settings()
    trace = LatencyTrace()
    evaluation_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    warnings: list[str] = []

    guard = get_guardrail_engine()

    # --- 1. Input guardrail ------------------------------------------------
    input_guard = await guard.check_input(request.query, trace=trace)
    if input_guard.status is GuardrailStatus.BLOCK:
        trace.finish()
        response = _blocked_response(
            evaluation_id=evaluation_id,
            created_at=created_at,
            request=request,
            guardrail=input_guard,
            trace=trace,
        )
        if db is not None:
            await trace_store.save(db, response, reference_answer=request.reference_answer)
        return response

    # --- 2. Retrieval ------------------------------------------------------
    retrieval = await retrieve(
        request.query, top_k=request.top_k, trace=trace, settings=settings
    )
    warnings.extend(retrieval.warnings)
    contexts: list[RetrievedChunk] = retrieval.chunks
    context_texts = retrieval.texts

    # --- 3. Context validation --------------------------------------------
    with trace.span(CONTEXT_VALIDATION):
        context_validation = await validate_context(
            request.query, context_texts, retrieval.similarities
        )

    # --- 4. Generation -----------------------------------------------------
    generation = await generate_answer(request.query, context_texts, trace=trace)
    answer = generation.answer
    if not generation.available and generation.error:
        warnings.append(generation.error)

    # --- 5. Output guardrail ----------------------------------------------
    output_guard = await guard.check_output(answer, trace=trace)
    guardrail = _merge_guardrails(input_guard, output_guard)

    # --- 5b. Moss evidence verification ------------------------------------
    # Second Moss stage: ask the corpus whether anything backs the *answer*,
    # which is a different question from what retrieval asked of the *query*.
    # Advisory only - it is not merged into the faithfulness context.
    moss_stages: list = []
    if retrieval.moss_record is not None:
        moss_stages.append(retrieval.moss_record)

    with trace.span(MOSS_EVIDENCE):
        moss_evidence, evidence_record = await verify_with_moss(answer, settings=settings)
    moss_stages.append(evidence_record)
    if evidence_record.engine_ms is not None:
        trace.record_ms("moss_evidence_engine", evidence_record.engine_ms)

    # --- 6. Evaluation -----------------------------------------------------
    with trace.span(EVALUATION):
        if generation.available and answer.strip() and context_texts:
            scores = await ragas_eval.evaluate_triad(
                query=request.query,
                contexts=context_texts,
                answer=answer,
            )
        else:
            scores = ragas_eval.unavailable_scores(
                _skip_reason(generation.available, bool(answer.strip()), bool(context_texts))
            )

        factual = await verify_against_reference(
            request.query, answer, request.reference_answer
        )

    # --- 7. Reliability gate ----------------------------------------------
    verdict = decide(
        faithfulness=scores.faithfulness,
        relevance=scores.answer_relevance,
        context_precision=scores.context_precision,
        context=context_validation,
        guardrail=guardrail,
        factual=factual,
        answer=answer,
        settings=settings,
    )
    warnings.extend(verdict.warnings)

    # Moss reports its own search time; record it alongside our wall clock so
    # the trace shows engine time versus total retrieval time.
    if retrieval.engine_ms is not None:
        trace.record_ms("moss_engine", retrieval.engine_ms)

    trace.finish()

    response = EvaluationResponse(
        evaluation_id=evaluation_id,
        created_at=created_at,
        channel=request.channel,
        query=request.query,
        contexts=contexts,
        answer=answer,
        faithfulness=scores.faithfulness,
        answer_relevance=scores.answer_relevance,
        context_precision=scores.context_precision,
        context_validation=context_validation,
        guardrail=guardrail,
        factual_verification=factual,
        status=verdict.status,
        explanation=verdict.explanation,
        supported=verdict.supported,
        retrieval_backend=retrieval.backend,
        moss_stages=[MossStageInfo(**r.to_dict()) for r in moss_stages],
        moss_evidence=moss_evidence,
        latency=LatencyBreakdown(**trace.to_dict()),
        warnings=_dedupe(warnings),
    )

    if db is not None:
        try:
            await trace_store.save(db, response, reference_answer=request.reference_answer)
        except Exception:
            # Losing the audit record must not lose the user's answer.
            logger.exception("Failed to persist trace %s", evaluation_id)
            response.warnings.append(
                "This evaluation could not be written to the trace store."
            )

    return response


async def evaluate_supplied_triad(
    *,
    query: str,
    contexts: list[str],
    answer: str,
    reference_answer: str | None = None,
    db: AsyncSession | None = None,
    channel: SourceChannel = SourceChannel.TEXT,
    settings: Settings | None = None,
) -> EvaluationResponse:
    """Evaluate a Query/Context/Answer triad without retrieval or generation.

    This is what makes the reliability test cases reproducible: the context and
    answer are pinned by the caller, so the result depends only on the evaluator.
    """
    settings = settings or get_settings()
    trace = LatencyTrace()
    evaluation_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)

    guard = get_guardrail_engine()
    input_guard = await guard.check_input(query, trace=trace)
    output_guard = await guard.check_output(answer, trace=trace)
    guardrail = _merge_guardrails(input_guard, output_guard)

    # Similarity against the supplied context, for the validation stage.
    from app.retrieval.faiss_store import get_faiss_store

    similarities = get_faiss_store().score_texts(query, contexts)

    with trace.span(CONTEXT_VALIDATION):
        context_validation = await validate_context(query, contexts, similarities)

    # Moss evidence verification applies here too: the context was supplied by
    # the caller, but the question "does the corpus back this answer?" is still
    # meaningful and is what this stage asks.
    with trace.span(MOSS_EVIDENCE):
        moss_evidence, evidence_record = await verify_with_moss(answer, settings=settings)
    if evidence_record.engine_ms is not None:
        trace.record_ms("moss_evidence_engine", evidence_record.engine_ms)

    with trace.span(EVALUATION):
        scores = await ragas_eval.evaluate_triad(
            query=query, contexts=contexts, answer=answer
        )
        factual = await verify_against_reference(query, answer, reference_answer)

    verdict = decide(
        faithfulness=scores.faithfulness,
        relevance=scores.answer_relevance,
        context_precision=scores.context_precision,
        context=context_validation,
        guardrail=guardrail,
        factual=factual,
        answer=answer,
        settings=settings,
    )
    trace.finish()

    response = EvaluationResponse(
        evaluation_id=evaluation_id,
        created_at=created_at,
        channel=channel,
        query=query,
        contexts=[
            RetrievedChunk(
                text=text,
                score=similarities[index] if index < len(similarities) else None,
                source="supplied",
            )
            for index, text in enumerate(contexts)
        ],
        answer=answer,
        faithfulness=scores.faithfulness,
        answer_relevance=scores.answer_relevance,
        context_precision=scores.context_precision,
        context_validation=context_validation,
        guardrail=guardrail,
        factual_verification=factual,
        status=verdict.status,
        explanation=verdict.explanation,
        supported=verdict.supported,
        retrieval_backend=RetrievalBackend.NONE,
        moss_stages=[MossStageInfo(**evidence_record.to_dict())],
        moss_evidence=moss_evidence,
        latency=LatencyBreakdown(**trace.to_dict()),
        warnings=_dedupe(verdict.warnings),
    )

    if db is not None:
        await trace_store.save(db, response, reference_answer=reference_answer)
    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _merge_guardrails(input_guard, output_guard):
    """Combine the input and output verdicts, worst status wins."""
    order = {GuardrailStatus.PASS: 0, GuardrailStatus.REVIEW: 1, GuardrailStatus.BLOCK: 2}
    worst = max((input_guard, output_guard), key=lambda g: order[g.status])
    if worst.status is GuardrailStatus.PASS:
        return worst

    triggered = list(dict.fromkeys(input_guard.triggered + output_guard.triggered))
    reasons = [
        f"[{guard.stage}] {guard.reason}"
        for guard in (input_guard, output_guard)
        if guard.status is not GuardrailStatus.PASS
    ]
    return worst.model_copy(
        update={"reason": " ".join(reasons), "triggered": triggered, "stage": worst.stage}
    )


def _skip_reason(generation_available: bool, has_answer: bool, has_context: bool) -> str:
    if not generation_available:
        return (
            "No answer was generated (the LLM is unavailable), so there is nothing "
            "to score."
        )
    if not has_context:
        return "No context was retrieved, so faithfulness to context is undefined."
    if not has_answer:
        return "The agent returned an empty answer, so there is nothing to score."
    return "Scoring was skipped."


def _blocked_response(
    *,
    evaluation_id: str,
    created_at: datetime,
    request: PipelineInput,
    guardrail,
    trace: LatencyTrace,
) -> EvaluationResponse:
    """Build the response for a query blocked before retrieval."""
    skipped = "The request was blocked by the input guardrail before this stage ran."
    return EvaluationResponse(
        evaluation_id=evaluation_id,
        created_at=created_at,
        channel=request.channel,
        query=request.query,
        contexts=[],
        answer="",
        faithfulness=MetricScore(status=MetricStatus.NOT_APPLICABLE, detail=skipped),
        answer_relevance=MetricScore(status=MetricStatus.NOT_APPLICABLE, detail=skipped),
        context_precision=MetricScore(status=MetricStatus.NOT_APPLICABLE, detail=skipped),
        context_validation=ContextValidation(
            status=ContextValidationStatus.EMPTY,
            reason=skipped,
            chunks_retrieved=0,
        ),
        guardrail=guardrail,
        factual_verification=FactualVerification(
            status=MetricStatus.NOT_APPLICABLE,
            reason=skipped,
        ),
        status=ReliabilityStatus.FAILED,
        explanation=(
            f"The query was blocked by the safety layer before retrieval: "
            f"{guardrail.reason} No context was retrieved and no answer was generated."
        ),
        supported=None,
        retrieval_backend=RetrievalBackend.NONE,
        latency=LatencyBreakdown(**trace.to_dict()),
        warnings=[],
    )


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))
