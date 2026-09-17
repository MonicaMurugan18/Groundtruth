"""RAGAS evaluation.

Three metrics, each measuring something different:

* **Faithfulness** - decomposes the answer into atomic claims and checks each one
  for entailment by the retrieved context. This is the hallucination signal.
  It says nothing about whether the context is true; see
  ``app.evaluation.factuality`` for that.
* **AnswerRelevancy** - generates questions the answer would be a good reply to
  and measures their similarity to the real question. Catches answers that are
  well-grounded but off-topic.
* **ContextUtilization** - context precision without a reference answer, which
  is the case here: it judges whether the retrieved chunks were actually useful.

Every metric is genuinely computed by RAGAS against a real LLM judge. If the
judge is unavailable the metric is reported as UNAVAILABLE with the reason
attached - it is never defaulted, estimated, or silently set to zero.

API verified against RAGAS 0.4 (``ragas.metrics.collections``).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.config.settings import get_settings
from app.schemas.common import MetricStatus
from app.schemas.evaluation import MetricScore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TriadScores:
    faithfulness: MetricScore
    answer_relevance: MetricScore
    context_precision: MetricScore


def unavailable_scores(reason: str, status: MetricStatus = MetricStatus.NOT_APPLICABLE) -> TriadScores:
    """Build a score bundle where nothing was computed, with the reason why."""
    return TriadScores(
        faithfulness=MetricScore(status=status, detail=reason),
        answer_relevance=MetricScore(status=status, detail=reason),
        context_precision=MetricScore(status=status, detail=reason),
    )


def _build_judge():
    """Construct the RAGAS LLM and embeddings, or raise.

    Both are pinned to the configured evaluation model at temperature 0 so the
    same triad scores the same way on a re-run.
    """
    settings = get_settings()
    if not settings.llm_configured:
        raise RuntimeError(
            "OPENAI_API_KEY is not set, so RAGAS metrics cannot be computed."
        )

    from openai import AsyncOpenAI
    from ragas.embeddings.base import embedding_factory
    from ragas.llms import llm_factory

    client_kwargs: dict = {"api_key": settings.openai_api_key}
    if settings.openai_base_url.strip():
        client_kwargs["base_url"] = settings.openai_base_url.strip()
    client = AsyncOpenAI(**client_kwargs)

    llm = llm_factory(settings.eval_llm_model, client=client)
    embeddings = embedding_factory("openai", model="text-embedding-3-small", client=client)
    return llm, embeddings


async def evaluate_triad(
    *,
    query: str,
    contexts: list[str],
    answer: str,
) -> TriadScores:
    """Score a Query/Context/Answer triad with RAGAS."""
    if not answer.strip():
        return unavailable_scores("The answer is empty, so there is nothing to score.")
    if not contexts:
        return unavailable_scores(
            "No context was retrieved, so faithfulness and context precision are "
            "undefined."
        )

    try:
        llm, embeddings = _build_judge()
    except Exception as exc:
        logger.info("RAGAS unavailable: %s", exc)
        return unavailable_scores(str(exc), status=MetricStatus.UNAVAILABLE)

    try:
        from ragas.metrics.collections import (
            AnswerRelevancy,
            ContextUtilization,
            Faithfulness,
        )
    except ImportError as exc:  # pragma: no cover - dependency guard
        return unavailable_scores(
            f"RAGAS metrics could not be imported: {exc}", status=MetricStatus.ERROR
        )

    # Run the three metrics concurrently; each makes its own judge calls.
    faithfulness_task = _score(
        "faithfulness",
        Faithfulness(llm=llm),
        user_input=query,
        response=answer,
        retrieved_contexts=contexts,
    )
    relevance_task = _score(
        "answer_relevance",
        AnswerRelevancy(llm=llm, embeddings=embeddings),
        user_input=query,
        response=answer,
    )
    precision_task = _score(
        "context_precision",
        ContextUtilization(llm=llm),
        user_input=query,
        response=answer,
        retrieved_contexts=contexts,
    )

    faithfulness, relevance, precision = await asyncio.gather(
        faithfulness_task, relevance_task, precision_task
    )
    return TriadScores(
        faithfulness=faithfulness,
        answer_relevance=relevance,
        context_precision=precision,
    )


async def _score(name: str, scorer, **kwargs) -> MetricScore:
    """Run one metric and normalise the result, never raising."""
    try:
        result = await scorer.ascore(**kwargs)
    except Exception as exc:
        logger.warning("RAGAS metric %s failed: %s", name, exc)
        return MetricScore(
            status=MetricStatus.ERROR,
            detail=f"{type(exc).__name__}: {exc}",
        )

    raw = getattr(result, "value", result)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return MetricScore(
            status=MetricStatus.ERROR,
            detail=f"RAGAS returned a non-numeric score for {name}: {raw!r}",
        )

    # RAGAS returns NaN when it cannot extract any claim to judge - for example
    # an answer with no verifiable statements. That is 'not applicable', not 0.
    if value != value:
        return MetricScore(
            status=MetricStatus.NOT_APPLICABLE,
            detail=(
                f"RAGAS could not compute {name}: the answer contains no verifiable "
                "claims to judge."
            ),
        )

    return MetricScore(value=min(max(value, 0.0), 1.0), status=MetricStatus.OK)
