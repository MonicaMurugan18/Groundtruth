"""Context validation: is the retrieved context usable at all?

This runs after retrieval and before the answer is judged, because the two
failure modes need different fixes. If the corpus never supplied the relevant
passage, the fault is in retrieval or ingestion, and scoring the generator's
answer would misattribute it.

Two signals are combined:

* **Embedding similarity** - always available, cheap, deterministic. Catches the
  blatant case where retrieved text is topically unrelated to the query.
* **An LLM judge** - available when an API key is configured. Catches the harder
  case where passages are on-topic but lack the specific detail asked for
  (for example, a leave policy retrieved for a refund question scores some
  similarity but cannot answer it).

When both are available the LLM verdict wins, since similarity cannot tell
"about the right subject" from "answers the question". The similarity numbers
are still recorded, so the trace shows what each signal said.
"""

from __future__ import annotations

import logging

from app.prompts.registry import build_context_block, get_prompt
from app.schemas.common import ContextValidationStatus
from app.schemas.evaluation import ContextValidation
from app.services.llm import LLMCallFailed, LLMNotConfigured, complete_structured

logger = logging.getLogger(__name__)

# Cosine bands for all-MiniLM-L6-v2. Used when no LLM judge is configured, and
# as the always-on sanity signal recorded alongside the LLM verdict.
IRRELEVANT_BELOW = 0.25
RELEVANT_ABOVE = 0.45


async def validate_context(
    query: str,
    contexts: list[str],
    similarities: list[float] | None = None,
) -> ContextValidation:
    """Classify retrieved context as relevant, insufficient, irrelevant or empty."""
    if not contexts:
        return ContextValidation(
            status=ContextValidationStatus.EMPTY,
            reason=(
                "Retrieval returned no context. The corpus may be empty, or no chunk "
                "was similar enough to the query. Ingest documents before querying."
            ),
            chunks_retrieved=0,
        )

    scores = [score for score in (similarities or []) if score is not None]
    max_similarity = max(scores) if scores else None
    mean_similarity = (sum(scores) / len(scores)) if scores else None

    heuristic = _heuristic_status(max_similarity)

    try:
        verdict = await _llm_verdict(query, contexts)
    except (LLMNotConfigured, LLMCallFailed) as exc:
        logger.info("Context validation falling back to similarity only: %s", exc)
        return ContextValidation(
            status=heuristic,
            reason=_heuristic_reason(heuristic, max_similarity, len(contexts)),
            chunks_retrieved=len(contexts),
            max_similarity=_round(max_similarity),
            mean_similarity=_round(mean_similarity),
        )

    status, reason, missing = verdict
    if missing and status is not ContextValidationStatus.RELEVANT:
        reason = f"{reason} Missing: {missing}"

    # Surface a disagreement rather than hiding it - it usually means the
    # retriever found the right topic but the wrong specifics.
    if status is ContextValidationStatus.RELEVANT and heuristic is ContextValidationStatus.IRRELEVANT:
        reason = (
            f"{reason} (Note: embedding similarity was low at "
            f"{_round(max_similarity)}, so this passage may be a weak match.)"
        )

    return ContextValidation(
        status=status,
        reason=reason,
        chunks_retrieved=len(contexts),
        max_similarity=_round(max_similarity),
        mean_similarity=_round(mean_similarity),
    )


async def _llm_verdict(
    query: str, contexts: list[str]
) -> tuple[ContextValidationStatus, str, str]:
    """Ask the judge whether the context can support an answer."""
    template = get_prompt("context_evaluation")
    payload = await complete_structured(
        template,
        temperature=0.0,
        query=query,
        context_block=build_context_block(contexts),
    )

    raw_status = str(payload.get("status", "")).strip().lower()
    try:
        status = ContextValidationStatus(raw_status)
    except ValueError as exc:
        raise LLMCallFailed(
            f"Context validator returned an unknown status {raw_status!r}."
        ) from exc

    reason = str(payload.get("reason") or "").strip() or "No reason given."
    missing = str(payload.get("missing_information") or "").strip()
    return status, reason, missing


def _heuristic_status(max_similarity: float | None) -> ContextValidationStatus:
    if max_similarity is None:
        return ContextValidationStatus.INSUFFICIENT
    if max_similarity < IRRELEVANT_BELOW:
        return ContextValidationStatus.IRRELEVANT
    if max_similarity >= RELEVANT_ABOVE:
        return ContextValidationStatus.RELEVANT
    return ContextValidationStatus.INSUFFICIENT


def _heuristic_reason(
    status: ContextValidationStatus, max_similarity: float | None, count: int
) -> str:
    similarity_text = (
        f"best cosine similarity {max_similarity:.2f}"
        if max_similarity is not None
        else "similarity unavailable"
    )
    base = f"Judged from embedding similarity only ({similarity_text}, {count} chunks). "
    if status is ContextValidationStatus.IRRELEVANT:
        return base + (
            "No retrieved chunk is close to the query, so the context is unlikely "
            "to support any answer."
        )
    if status is ContextValidationStatus.RELEVANT:
        return base + "At least one chunk is a strong semantic match for the query."
    return base + (
        "Retrieved chunks are only loosely related to the query, so they may not "
        "contain the specific detail asked for. Configure an LLM provider key "
        "for a stronger sufficiency check."
    )


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 4)
