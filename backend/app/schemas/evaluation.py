"""Request/response contracts for the evaluation pipeline.

These models are the single source of truth for the shape the Next.js dashboard
consumes. They also encode the central epistemic distinction of this project:

* **Faithfulness** answers "is the answer supported by the retrieved context?"
* **Factual verification** answers "is the context itself actually true?"

RAGAS measures only the former. The two are modelled as separate fields so the
UI can never present grounding as proof of truth.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import (
    ContextValidationStatus,
    GuardrailStatus,
    MetricStatus,
    ReliabilityStatus,
    RetrievalBackend,
    SourceChannel,
)


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    """A user question to run through the full RAG + evaluation pipeline."""

    query: str = Field(min_length=1, max_length=4000, description="The user's question.")
    top_k: int | None = Field(default=None, ge=1, le=20)
    channel: SourceChannel = SourceChannel.TEXT
    reference_answer: str | None = Field(
        default=None,
        max_length=4000,
        description=(
            "Optional known-correct answer. When supplied, Groundtruth performs "
            "ground-truth comparison in addition to faithfulness-to-context."
        ),
    )

    @field_validator("query", "reference_answer")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class EvaluateTriadRequest(BaseModel):
    """Evaluate a Query/Context/Answer triad supplied by the caller.

    This bypasses retrieval and generation, which is what makes the reliability
    tests reproducible: the harness pins the context and answer, so the scores
    depend only on the evaluator.
    """

    query: str = Field(min_length=1, max_length=4000)
    contexts: list[str] = Field(min_length=1, max_length=50)
    answer: str = Field(min_length=1, max_length=8000)
    reference_answer: str | None = Field(default=None, max_length=4000)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


class RetrievedChunk(BaseModel):
    """One piece of context handed to the LLM, exactly as retrieved."""

    text: str
    score: float | None = None
    source: str | None = None
    chunk_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MetricScore(BaseModel):
    """A single evaluation metric with provenance.

    ``value`` is ``None`` whenever ``status`` is not ``OK``. Consumers must
    render "unavailable" in that case rather than defaulting to zero.
    """

    value: float | None = Field(default=None, ge=0.0, le=1.0)
    status: MetricStatus = MetricStatus.OK
    detail: str | None = None

    @property
    def percent(self) -> float | None:
        return None if self.value is None else round(self.value * 100, 1)


class ContextValidation(BaseModel):
    """Result of checking retrieval quality *before* judging the answer."""

    status: ContextValidationStatus
    reason: str
    chunks_retrieved: int
    max_similarity: float | None = None
    mean_similarity: float | None = None


class GuardrailResult(BaseModel):
    """Structured output of the safety/policy layer."""

    status: GuardrailStatus
    reason: str
    triggered: list[str] = Field(
        default_factory=list, description="Identifiers of the validators that fired."
    )
    stage: str = Field(default="output", description="'input' or 'output'.")


class FactualVerification(BaseModel):
    """Ground-truth comparison, kept strictly separate from faithfulness.

    Only meaningful when a reference answer is supplied. Without one, the status
    is ``NOT_APPLICABLE`` and Groundtruth makes no claim about factual accuracy.
    """

    status: MetricStatus = MetricStatus.NOT_APPLICABLE
    correct: bool | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str = (
        "No reference answer was supplied, so factual correctness was not assessed. "
        "Faithfulness measures support by the retrieved context only."
    )


class LatencyBreakdown(BaseModel):
    """Per-stage wall-clock timings, in milliseconds."""

    model_config = ConfigDict(extra="allow")

    retrieval_ms: float | None = None
    llm_ms: float | None = None
    guardrail_ms: float | None = None
    evaluation_ms: float | None = None
    context_validation_ms: float | None = None
    total_ms: float


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class EvaluationResponse(BaseModel):
    """The complete trust report for one interaction."""

    evaluation_id: str
    created_at: datetime
    channel: SourceChannel

    # The RAG triad
    query: str
    contexts: list[RetrievedChunk]
    answer: str

    # Scores
    faithfulness: MetricScore
    answer_relevance: MetricScore
    context_precision: MetricScore

    # Separate stages
    context_validation: ContextValidation
    guardrail: GuardrailResult
    factual_verification: FactualVerification

    # Verdict
    status: ReliabilityStatus
    explanation: str
    supported: bool | None = None

    # Observability
    retrieval_backend: RetrievalBackend
    latency: LatencyBreakdown
    warnings: list[str] = Field(default_factory=list)


class TraceSummary(BaseModel):
    """Row shape for the evaluation history table."""

    evaluation_id: str
    created_at: datetime
    query: str
    status: ReliabilityStatus
    channel: SourceChannel
    faithfulness: float | None = None
    answer_relevance: float | None = None
    guardrail_status: GuardrailStatus
    total_ms: float | None = None


class DashboardStats(BaseModel):
    """Aggregate metrics for the dashboard landing page."""

    total_evaluations: int
    reliable_count: int
    needs_review_count: int
    failed_count: int
    guardrail_violations: int
    avg_faithfulness: float | None = None
    avg_relevance: float | None = None
    avg_context_precision: float | None = None
    avg_latency_ms: float | None = None
    voice_evaluations: int = 0
    recent: list[TraceSummary] = Field(default_factory=list)
