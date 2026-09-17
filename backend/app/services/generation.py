"""Grounded answer generation.

Uses the ``rag_answer`` CRISPE template, which instructs the model to answer
only from the supplied passages and to say so plainly when they do not cover the
question. That abstention path is a feature: "the context does not cover this"
is a correct, high-reliability outcome, whereas a confident guess is the exact
behaviour Groundtruth exists to catch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.prompts.registry import build_context_block, get_prompt
from app.services.llm import LLMCallFailed, LLMNotConfigured, complete_structured
from app.tracing.timer import LLM, LatencyTrace

logger = logging.getLogger(__name__)

NO_LLM_MESSAGE = (
    "No answer was generated because no LLM is configured. Set OPENAI_API_KEY in "
    "backend/.env to enable answer generation."
)


@dataclass(slots=True)
class GenerationResult:
    answer: str
    answer_found: bool
    context_used: list[int] = field(default_factory=list)
    available: bool = True
    error: str | None = None


async def generate_answer(
    query: str,
    contexts: list[str],
    *,
    trace: LatencyTrace | None = None,
) -> GenerationResult:
    """Generate an answer grounded in ``contexts``.

    Never raises for a configuration or provider problem: it returns an
    unavailable result so the rest of the pipeline can still record a trace
    showing exactly which stage failed.
    """
    template = get_prompt("rag_answer")
    context_block = build_context_block(contexts)

    async def _call() -> GenerationResult:
        payload = await complete_structured(
            template,
            query=query,
            context_block=context_block,
        )
        answer = str(payload.get("answer") or "").strip()
        raw_used = payload.get("context_used") or []
        used = [int(index) for index in raw_used if isinstance(index, (int, float))]
        return GenerationResult(
            answer=answer,
            answer_found=bool(payload.get("answer_found")),
            context_used=used,
        )

    try:
        if trace is not None:
            with trace.span(LLM):
                return await _call()
        return await _call()
    except LLMNotConfigured as exc:
        logger.info("Generation skipped: %s", exc)
        return GenerationResult(
            answer=NO_LLM_MESSAGE,
            answer_found=False,
            available=False,
            error=str(exc),
        )
    except LLMCallFailed as exc:
        logger.warning("Generation failed: %s", exc)
        return GenerationResult(
            answer="",
            answer_found=False,
            available=False,
            error=str(exc),
        )
