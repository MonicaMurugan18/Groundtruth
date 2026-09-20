"""Groundtruth orchestrator API.

FastAPI application factory. Wires configuration, security, the trace store and
the route modules together. Pipeline logic lives in ``app.services`` and the
stage packages; this module only assembles them.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.routes import auth, evaluation, health, ingest, traces, voice
from app.api.security import assert_production_security, limiter
from app.config.settings import get_settings
from app.db.session import close_db, init_db
from app.services.warmup import warm_up

logger = logging.getLogger(__name__)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start-up and shutdown for the orchestrator."""
    settings = get_settings()
    _configure_logging(settings.log_level)

    # Fail fast rather than serving an insecure production deployment.
    assert_production_security(settings)

    settings.faiss_path.mkdir(parents=True, exist_ok=True)
    settings.uploads_path.mkdir(parents=True, exist_ok=True)

    await init_db()

    if not settings.llm_configured:
        logger.warning(
            "%s is not set for LLM_PROVIDER=%s. Answer generation and RAGAS scoring "
            "will be reported as unavailable; Groundtruth will not substitute "
            "placeholder scores.",
            settings.llm_key_variable,
            settings.active_provider,
        )
    else:
        logger.info(
            "LLM provider: %s (generation: %s, judge: %s)",
            settings.active_provider,
            settings.active_llm_model,
            settings.active_eval_model,
        )
    if not settings.moss_configured:
        logger.warning(
            "Moss credentials are not set. Retrieval will fall back to FAISS and every "
            "trace will be labelled with the backend that actually served it."
        )

    # Warm the expensive lazy components in the background so the first user
    # request is not charged ~23s of model loading and imports.
    warmup_task = asyncio.create_task(warm_up())

    logger.info("Groundtruth orchestrator ready (env=%s)", settings.app_env)
    try:
        yield
    finally:
        warmup_task.cancel()
        with suppress(asyncio.CancelledError):
            await warmup_task
        await close_db()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Groundtruth",
        description=(
            "A reliability and security layer for RAG agents. Evaluates every "
            "interaction for faithfulness to retrieved context, answer relevance, "
            "retrieval quality, safety and latency."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # --- Rate limiting ---
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded. Slow down and retry shortly.",
                "limit": str(exc.detail),
            },
        )

    # --- CORS: an explicit allowlist, never a wildcard with credentials ---
    origins = settings.cors_origin_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # --- Routes ---
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(ingest.router)
    app.include_router(evaluation.router)
    app.include_router(traces.router)
    app.include_router(voice.router)

    return app


app = create_app()
