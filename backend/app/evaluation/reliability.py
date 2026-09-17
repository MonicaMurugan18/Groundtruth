"""The reliability gate: turning scores into a verdict and an explanation.

This logic is deliberately deterministic. The brief is explicit that critical
evaluation logic must not rest on free-form model output, so the LLM's role ends
at producing individual metrics; combining them into RELIABLE / NEEDS REVIEW /
FAILED happens here, in code that can be read, unit-tested and argued with.

Precedence, strongest first:

1. **Guardrail BLOCK** - a safety failure is terminal regardless of scores.
2. **Context EMPTY or IRRELEVANT** - retrieval failed, so the answer cannot be
   trusted whatever it says. Reported as a retrieval fault, not a generator one.
3. **Faithfulness below threshold** - the answer asserts things the context does
   not support. This is the core hallucination signal.
4. **Factual contradiction** - where a reference answer was supplied and the
   answer contradicts it. Kept separate from faithfulness on purpose: an answer
   can be faithful to a passage that is itself wrong.
5. **Relevance / context precision / unavailable metrics** - degrade to
   NEEDS REVIEW rather than failing outright.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import Settings, get_settings
from app.schemas.common import (
    ContextValidationStatus,
    GuardrailStatus,
    MetricStatus,
    ReliabilityStatus,
)
from app.schemas.evaluation import (
    ContextValidation,
    FactualVerification,
    GuardrailResult,
    MetricScore,
)


@dataclass(slots=True)
class Verdict:
    status: ReliabilityStatus
    explanation: str
    supported: bool | None
    warnings: list[str]


def decide(
    *,
    faithfulness: MetricScore,
    relevance: MetricScore,
    context_precision: MetricScore,
    context: ContextValidation,
    guardrail: GuardrailResult,
    factual: FactualVerification,
    answer: str,
    settings: Settings | None = None,
) -> Verdict:
    """Combine every signal into a final status plus a human-readable rationale."""
    settings = settings or get_settings()
    reasons: list[str] = []
    warnings: list[str] = []

    # --- 1. Guardrails are terminal -------------------------------------
    if guardrail.status is GuardrailStatus.BLOCK:
        return Verdict(
            status=ReliabilityStatus.FAILED,
            explanation=(
                f"Blocked by the safety layer: {guardrail.reason} "
                "The response was withheld, so the answer quality metrics were not "
                "the deciding factor."
            ),
            supported=None,
            warnings=warnings,
        )

    # --- 2. Retrieval quality -------------------------------------------
    if context.status is ContextValidationStatus.EMPTY:
        return Verdict(
            status=ReliabilityStatus.FAILED,
            explanation=(
                "No context was retrieved, so nothing grounds this answer. "
                f"{context.reason} This is a retrieval failure rather than a "
                "generation failure - check that documents have been ingested."
            ),
            supported=False,
            warnings=warnings,
        )

    if context.status is ContextValidationStatus.IRRELEVANT:
        return Verdict(
            status=ReliabilityStatus.FAILED,
            explanation=(
                "The retrieved context does not address the question, so the answer "
                f"cannot be supported by it. {context.reason} Fix retrieval or ingest "
                "the relevant document before judging the agent's answer."
            ),
            supported=False,
            warnings=warnings,
        )

    if context.status is ContextValidationStatus.INSUFFICIENT:
        reasons.append(
            "the retrieved context is only partially relevant, so some of the answer "
            "may not be grounded"
        )

    # --- 3. Faithfulness -------------------------------------------------
    supported: bool | None = None
    faithfulness_failed = False

    if faithfulness.status is MetricStatus.OK and faithfulness.value is not None:
        supported = faithfulness.value >= settings.faithfulness_threshold
        if not supported:
            faithfulness_failed = True
            reasons.append(
                f"faithfulness is {faithfulness.value:.0%}, below the "
                f"{settings.faithfulness_threshold:.0%} threshold, meaning parts of the "
                "answer are not supported by the retrieved context"
            )
    else:
        warnings.append(
            f"Faithfulness could not be computed ({faithfulness.status.value})"
            + (f": {faithfulness.detail}" if faithfulness.detail else "")
        )

    # --- 4. Factual contradiction (separate from faithfulness) -----------
    if factual.status is MetricStatus.OK and factual.correct is False:
        return Verdict(
            status=ReliabilityStatus.FAILED,
            explanation=_compose(
                ReliabilityStatus.FAILED,
                [
                    "the answer contradicts the supplied reference answer, so it is "
                    f"factually incorrect ({factual.reason})",
                    *reasons,
                ],
                faithfulness,
                supported,
            ),
            supported=supported,
            warnings=warnings,
        )

    # --- 5. Softer signals -----------------------------------------------
    relevance_failed = False
    if relevance.status is MetricStatus.OK and relevance.value is not None:
        if relevance.value < settings.relevance_threshold:
            relevance_failed = True
            reasons.append(
                f"answer relevance is {relevance.value:.0%}, below the "
                f"{settings.relevance_threshold:.0%} threshold, meaning the answer "
                "drifts from what was actually asked"
            )
    else:
        warnings.append(f"Answer relevance could not be computed ({relevance.status.value})")

    if context_precision.status is MetricStatus.OK and context_precision.value is not None:
        if context_precision.value < settings.context_precision_threshold:
            reasons.append(
                f"retrieval quality is {context_precision.value:.0%}, below the "
                f"{settings.context_precision_threshold:.0%} threshold, so the "
                "retriever returned mostly unhelpful chunks"
            )
    else:
        warnings.append(
            f"Context precision could not be computed ({context_precision.status.value})"
        )

    if not answer.strip():
        return Verdict(
            status=ReliabilityStatus.FAILED,
            explanation="The agent produced an empty answer.",
            supported=False,
            warnings=warnings,
        )

    # --- Final status -----------------------------------------------------
    if faithfulness_failed:
        status = ReliabilityStatus.FAILED
    elif reasons or relevance_failed or guardrail.status is GuardrailStatus.REVIEW:
        status = ReliabilityStatus.NEEDS_REVIEW
    elif warnings:
        # Metrics missing entirely: we cannot certify reliability, so we say so
        # rather than passing by default.
        status = ReliabilityStatus.NEEDS_REVIEW
    else:
        status = ReliabilityStatus.RELIABLE

    if guardrail.status is GuardrailStatus.REVIEW:
        reasons.append(f"the safety layer flagged it for review ({guardrail.reason})")

    return Verdict(
        status=status,
        explanation=_compose(status, reasons, faithfulness, supported, warnings),
        supported=supported,
        warnings=warnings,
    )


def _compose(
    status: ReliabilityStatus,
    reasons: list[str],
    faithfulness: MetricScore,
    supported: bool | None,
    warnings: list[str] | None = None,
) -> str:
    """Build the sentence shown in the UI under 'why did this pass or fail?'."""
    warnings = warnings or []

    if status is ReliabilityStatus.RELIABLE:
        score_text = (
            f" Faithfulness is {faithfulness.value:.0%}"
            if faithfulness.value is not None
            else ""
        )
        return (
            "Every claim in the answer is supported by the retrieved context, and the "
            f"answer addresses the question asked.{score_text}. Note that this measures "
            "grounding in the supplied context, not independent factual truth."
        )

    lead = (
        "This answer failed the reliability gate because "
        if status is ReliabilityStatus.FAILED
        else "This answer needs review because "
    )

    if reasons:
        body = _join(reasons) + "."
    elif warnings:
        body = (
            "one or more evaluation metrics could not be computed, so reliability "
            "cannot be certified: " + _join(warnings) + "."
        )
    else:
        body = "the evaluator could not confirm it meets the configured thresholds."

    tail = ""
    if supported is False:
        tail = (
            " The specific problem is grounding: the answer states something the "
            "retrieved context does not say."
        )
    return lead + body + tail


def _join(items: list[str]) -> str:
    """Join clauses into readable prose."""
    unique = list(dict.fromkeys(items))
    if len(unique) == 1:
        return unique[0]
    if len(unique) == 2:
        return f"{unique[0]} and {unique[1]}"
    return ", ".join(unique[:-1]) + f", and {unique[-1]}"
