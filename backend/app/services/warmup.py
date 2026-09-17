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

    started = time.perf_counter()
    try:
        from app.guardrails.engine import get_guardrail_engine

        engine = get_guardrail_engine()
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
                "Warm-up: openai client ready in %.1fs",
                time.perf_counter() - started,
            )
        except Exception:
            logger.exception("Warm-up: openai import failed")


async def warm_up() -> None:
    """Warm every lazily-initialised component without blocking the event loop."""
    started = time.perf_counter()
    await asyncio.to_thread(_warm_sync)
    logger.info("Warm-up complete in %.1fs", time.perf_counter() - started)
