"""Ground-truth verification, kept separate from faithfulness.

This module exists because of a distinction the rest of the industry routinely
blurs. RAGAS faithfulness asks:

    "Is every claim in the answer entailed by the retrieved context?"

It does **not** ask whether the retrieved context is true. An agent that
faithfully repeats a stale policy document scores high faithfulness while
telling the user something false.

Groundtruth therefore treats factual correctness as a separate stage that runs
only when the caller supplies a reference answer. With no reference, the result
is ``NOT_APPLICABLE`` and the system makes no truth claim at all - which is the
honest outcome, and is rendered as such in the UI.
"""

from __future__ import annotations

import logging

from app.prompts.registry import get_prompt
from app.schemas.common import MetricStatus
from app.schemas.evaluation import FactualVerification
from app.services.llm import LLMCallFailed, LLMNotConfigured, complete_structured

logger = logging.getLogger(__name__)

NOT_ASSESSED_REASON = (
    "No reference answer was supplied, so factual correctness was not assessed. "
    "Faithfulness measures support by the retrieved context only, and a faithful "
    "answer can still be factually wrong if the context itself is wrong or stale."
)


async def verify_against_reference(
    query: str,
    answer: str,
    reference_answer: str | None,
) -> FactualVerification:
    """Compare ``answer`` to a known-correct ``reference_answer``."""
    if not reference_answer or not reference_answer.strip():
        return FactualVerification(
            status=MetricStatus.NOT_APPLICABLE,
            reason=NOT_ASSESSED_REASON,
        )

    if not answer.strip():
        return FactualVerification(
            status=MetricStatus.OK,
            correct=False,
            score=0.0,
            reason="The agent produced no answer, so it cannot match the reference.",
        )

    template = get_prompt("groundtruth_comparison")
    try:
        payload = await complete_structured(
            template,
            temperature=0.0,
            query=query,
            answer=answer,
            reference_answer=reference_answer,
        )
    except LLMNotConfigured as exc:
        return FactualVerification(
            status=MetricStatus.UNAVAILABLE,
            reason=(
                "A reference answer was supplied but no LLM is configured, so factual "
                f"verification could not run. {exc}"
            ),
        )
    except LLMCallFailed as exc:
        logger.warning("Ground-truth comparison failed: %s", exc)
        return FactualVerification(
            status=MetricStatus.ERROR,
            reason=f"Factual verification failed to run: {exc}",
        )

    correct = bool(payload.get("correct"))
    raw_score = payload.get("score")
    try:
        score = min(max(float(raw_score), 0.0), 1.0) if raw_score is not None else None
    except (TypeError, ValueError):
        score = None

    reason = str(payload.get("reason") or "").strip() or "No reason given."
    contradictions = [str(item) for item in (payload.get("contradictions") or [])]
    if contradictions:
        reason = f"{reason} Contradictions: {'; '.join(contradictions)}"

    return FactualVerification(
        status=MetricStatus.OK,
        correct=correct,
        score=score,
        reason=reason,
    )
