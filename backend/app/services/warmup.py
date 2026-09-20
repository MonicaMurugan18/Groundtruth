"""Startup warm-up for lazily-initialised components.

Several dependencies are expensive on first use and cheap thereafter:

* the Hugging Face embedding model (loading weights)
* ``guardrails.hub`` (its import chain pulls in litellm)
* the ``openai`` client module
* the FAISS index (read from disk)

Left lazy, all of that cost lands on the first user request, which measured
roughly 23 seconds against 68 milliseconds warm. That is a genuine cost, not one
we want to hide, so it is paid here at startup and logged, rather than being
charged to whoever asks the first question.

Runs as a background task so the server starts accepting connections
immediately. A failure here is logged and ignored: warm-up is an optimisation,
and each component still initialises lazily on demand.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


def _warm_sync() -> None:
    """Blocking warm-up, run in a worker thread."""
    settings = get_settings()

    started = time.perf_counter()
    try:
        from app.retrieval.embeddings import get_embedding_model

        get_embedding_model()
        logger.info(
            "Warm-up: embedding model ready in %.1fs",
            time.perf_counter() - started,
        )
    except Exception:
        logger.exception("Warm-up: embedding model failed to load")

    started = time.perf_counter()
    try:
        from app.retrieval.faiss_store import get_faiss_store

        store = get_faiss_store()
        store.load()
        logger.info(
            "Warm-up: FAISS index ready in %.1fs (%d chunks)",
            time.perf_counter() - started,
            store.size,
        )
    except Exception:
        logger.exception("Warm-up: FAISS index failed to load")

    if settings.moss_configured:
        started = time.perf_counter()
        try:
            import asyncio as _asyncio

            from app.integrations.moss.client import get_moss_retriever

            # Loading a Moss index measured 13s on the first query. Without this
            # the whole cost lands on whoever asks the first question, exactly
            # like the embedding model did.
            _asyncio.run(get_moss_retriever().ensure_loaded())
            logger.info(
                "Warm-up: Moss index %r ready in %.1fs",
                settings.moss_index_name,
                time.perf_counter() - started,
            )
        except Exception as exc:
            # Non-fatal: retrieval falls back to FAISS and says so.
            logger.warning(
                "Warm-up: Moss index %r could not be preloaded (%s); retrieval will "
                "fall back to FAISS until it loads",
                settings.moss_index_name,
                exc,
            )

    started = time.perf_counter()
    try:
        from app.guardrails.engine import get_guardrail_engine

        engine = get_guardrail_engine()
        engine.active_validators()

        # Run one throwaway validation so a validator that loads but cannot
        # execute (a missing model file, a restricted cache path) is discovered
        # and quarantined here, where it is logged - not on the first user
        # request, which would otherwise be flagged NEEDS_REVIEW for a fault
        # that has nothing to do with the answer.
        try:
            import asyncio as _asyncio

            _asyncio.run(engine.check_output("Warm-up probe."))
        except Exception:
            logger.debug("Warm-up: guardrail probe failed", exc_info=True)

        validators = engine.active_validators()
        logger.info(
            "Warm-up: guardrails ready in %.1fs (%d active validators)",
            time.perf_counter() - started,
            len(validators),
        )
    except Exception:
        logger.exception("Warm-up: guardrails failed to initialise")

    if settings.llm_configured:
        started = time.perf_counter()
        try:
            import openai  # noqa: F401

            logger.info(
                "Warm-up: %s client ready in %.1fs",
                settings.active_provider,
                time.perf_counter() - started,
            )
        except Exception:
            logger.exception("Warm-up: LLM client import failed")

        started = time.perf_counter()
        try:
            from app.evaluation.ragas_eval import _build_judge

            # RAGAS builds its own embedding instance, separate from the one
            # retrieval uses. Left cold, that model is fetched on the first
            # evaluation - over a throttled anonymous Hugging Face connection
            # that dominated the first request. Build it here instead.
            _build_judge()
            logger.info(
                "Warm-up: RAGAS judge ready in %.1fs (judge model %s, local embeddings)",
                time.perf_counter() - started,
                settings.active_eval_model,
            )
        except Exception as exc:
            logger.warning(
                "Warm-up: RAGAS judge could not be preloaded (%s); it will be built "
                "on first evaluation",
                exc,
            )


async def warm_up() -> None:
    """Warm every lazily-initialised component without blocking the event loop."""
    started = time.perf_counter()
    await asyncio.to_thread(_warm_sync)
    logger.info("Warm-up complete in %.1fs", time.perf_counter() - started)
