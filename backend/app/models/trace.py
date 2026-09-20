"""ORM models for the PostgreSQL trace store.

Schema notes
------------
* ``EvaluationTrace`` holds one row per interaction: the RAG triad, every score,
  the guardrail verdict, per-stage latency and the final reliability status.
* ``RetrievedContext`` is a child table holding the individual chunks that were
  actually supplied to the LLM, preserving rank and similarity so a failure can
  be attributed to retrieval rather than generation.
* Score columns are nullable on purpose. NULL means "not computed" (no LLM judge
  configured, or the evaluator errored) and is rendered as *unavailable*, never
  as a zero score. The companion ``*_status`` columns record which case applies.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class EvaluationTrace(Base):
    """A complete, auditable record of one evaluated interaction."""

    __tablename__ = "evaluation_traces"

    evaluation_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_id
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )

    # --- The RAG triad ---
    user_query: Mapped[str] = mapped_column(Text, nullable=False)
    agent_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Channel / provenance ---
    channel: Mapped[str] = mapped_column(
        String(16), default="text", nullable=False, index=True
    )
    retrieval_backend: Mapped[str] = mapped_column(
        String(16), default="none", nullable=False
    )

    # --- Moss ---
    # Scalar status of the PRIMARY retrieval call, indexed so the dashboard can
    # filter/aggregate on "did Moss serve this?" without unpacking JSON.
    moss_status: Mapped[str] = mapped_column(
        String(20), default="skipped", nullable=False, index=True
    )
    # Every Moss call made for this interaction, in order, each with its own
    # status, timing and verbatim error. Kept as JSON rather than more columns
    # because the number of Moss stages is a pipeline detail, not a schema one.
    moss_stages: Mapped[list] = mapped_column(JSON, default=list)
    # Corroborating-evidence summary from the second Moss stage.
    moss_evidence: Mapped[dict] = mapped_column(JSON, default=dict)

    # --- RAGAS scores (NULL == not computed) ---
    faithfulness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    faithfulness_status: Mapped[str] = mapped_column(String(20), default="unavailable")
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    relevance_status: Mapped[str] = mapped_column(String(20), default="unavailable")
    retrieval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    retrieval_status: Mapped[str] = mapped_column(String(20), default="unavailable")

    # Per-metric explanation, keyed by metric name. Carries the reason a metric
    # was not computed ("no answer was generated", "RAGAS found no verifiable
    # claims"). Without this the stored trace can only say "not computed", while
    # the live response explained why — and the trace view is the thing people
    # come back to when debugging a failure.
    metric_details: Mapped[dict] = mapped_column(JSON, default=dict)

    # --- Context validation ---
    context_status: Mapped[str] = mapped_column(
        String(20), default="empty", nullable=False
    )
    context_reason: Mapped[str] = mapped_column(Text, default="")
    chunks_retrieved: Mapped[int] = mapped_column(Integer, default=0)
    max_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Guardrails ---
    guardrail_status: Mapped[str] = mapped_column(
        String(16), default="pass", nullable=False, index=True
    )
    guardrail_reason: Mapped[str] = mapped_column(Text, default="")
    guardrail_triggered: Mapped[list] = mapped_column(JSON, default=list)

    # --- Factual verification (distinct from faithfulness) ---
    factual_status: Mapped[str] = mapped_column(String(20), default="not_applicable")
    factual_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    factual_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    factual_reason: Mapped[str] = mapped_column(Text, default="")

    # --- Latency (ms). Individual columns so they aggregate in SQL;
    #     latency_detail keeps the full span map for the trace view. ---
    retrieval_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    guardrail_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    evaluation_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_validation_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_ms: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    latency_detail: Mapped[dict] = mapped_column(JSON, default=dict)

    # --- Verdict ---
    reliability_status: Mapped[str] = mapped_column(
        String(20), default="failed", nullable=False, index=True
    )
    supported: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, default="")
    warnings: Mapped[list] = mapped_column(JSON, default=list)

    contexts: Mapped[list["RetrievedContext"]] = relationship(
        back_populates="trace",
        cascade="all, delete-orphan",
        order_by="RetrievedContext.rank",
        lazy="selectin",
    )

    __table_args__ = (Index("ix_traces_status_created", "reliability_status", "created_at"),)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<EvaluationTrace {self.evaluation_id} "
            f"status={self.reliability_status}>"
        )


class RetrievedContext(Base):
    """One retrieved chunk that was supplied to the LLM for a given trace."""

    __tablename__ = "retrieved_contexts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    trace_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_traces.evaluation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    rank: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(512), nullable=True)
    chunk_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    doc_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    trace: Mapped[EvaluationTrace] = relationship(back_populates="contexts")
