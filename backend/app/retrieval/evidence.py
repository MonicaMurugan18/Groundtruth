"""Moss evidence verification.

The second Moss stage. After the agent has written an answer, the answer text
itself is used as a Moss query, asking the corpus a different question from the
one retrieval asked:

    retrieval    : "what does the corpus have about this *question*?"
    verification : "does the corpus contain anything backing this *answer*?"

Why this is worth a second call
-------------------------------
Retrieval is driven by the user's wording. An answer can introduce specifics the
question never mentioned - a number, a date, a qualifier - and those specifics
are exactly where hallucinations live. Querying the corpus with the answer finds
whether independent support for that wording exists, which retrieval alone
cannot tell you.

What this is NOT
----------------
This does not prove the answer is true, and it is deliberately not merged into
the context that RAGAS scores faithfulness against. Faithfulness must stay a
measure of "is the answer supported by what the model was actually shown". The
evidence signal is recorded alongside as corroboration, and the reliability gate
treats it as advisory only.

It uses the same verified ``MossClient.query`` API as retrieval - no additional
Moss capability is assumed.
"""

from __future__ import annotations

import logging

from app.config.settings import Settings, get_settings
from app.integrations.moss.client import (
    MossStage,
    MossStageRecord,
    MossStatus,
    get_moss_retriever,
)
from app.schemas.evaluation import MossEvidence

logger = logging.getLogger(__name__)

# Moss queries are semantic; an over-long answer dilutes the signal. Answers are
# truncated to a reasonable query length rather than sent whole.
MAX_QUERY_CHARS = 400


def _skipped(reason: str, query: str | None = None) -> tuple[MossEvidence, MossStageRecord]:
    record = MossStageRecord(
        stage=MossStage.EVIDENCE_VERIFICATION,
        status=MossStatus.SKIPPED,
        query=query,
        error=reason,
    )
    return MossEvidence(status=MossStatus.SKIPPED.value, reason=reason), record


async def verify_with_moss(
    answer: str,
    *,
    settings: Settings | None = None,
) -> tuple[MossEvidence, MossStageRecord]:
    """Query Moss with the answer text to look for corroborating evidence.

    Never raises. Returns the evidence summary plus the auditable stage record.
    """
    settings = settings or get_settings()

    if not settings.moss_evidence_enabled:
        return _skipped("Moss evidence verification is disabled (MOSS_EVIDENCE_ENABLED=false).")
    if not settings.moss_configured:
        evidence, record = _skipped("Moss is not configured.")
        record.status = MossStatus.NOT_CONFIGURED
        evidence.status = MossStatus.NOT_CONFIGURED.value
        return evidence, record
    if not answer or not answer.strip():
        return _skipped("No answer was produced, so there was nothing to corroborate.")

    query = answer.strip()[:MAX_QUERY_CHARS]
    retriever = get_moss_retriever()
    result, record = await retriever.search_recorded(
        query, stage=MossStage.EVIDENCE_VERIFICATION, top_k=settings.moss_evidence_top_k
    )

    if result is None:
        return (
            MossEvidence(
                status=record.status.value,
                reason=(
                    f"Moss could not be queried for corroborating evidence: {record.error}"
                ),
            ),
            record,
        )

    if not result.hits:
        return (
            MossEvidence(
                status=MossStatus.EMPTY.value,
                match_count=0,
                engine_ms=result.time_taken_ms,
                reason=(
                    "Moss found no passage in the corpus resembling this answer. That "
                    "is a signal worth inspecting, not proof the answer is wrong."
                ),
            ),
            record,
        )

    scores = [hit.score for hit in result.hits if hit.score is not None]
    top = max(scores) if scores else None
    snippets = [hit.text.strip() for hit in result.hits[:3] if hit.text.strip()]

    return (
        MossEvidence(
            status=MossStatus.SUCCESS.value,
            match_count=len(result.hits),
            top_score=top,
            engine_ms=result.time_taken_ms,
            snippets=snippets,
            reason=(
                f"Moss found {len(result.hits)} corpus passage(s) resembling the answer"
                + (f" (best score {top:.3f})" if top is not None else "")
                + ". This corroborates that the answer's wording appears in the "
                "corpus; it does not establish that the answer is true."
            ),
        ),
        record,
    )
