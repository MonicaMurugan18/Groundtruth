"""Query and evaluation endpoints."""

# NOTE: deliberately no `from __future__ import annotations` here.
# slowapi's @limiter.limit wrapper makes FastAPI resolve type hints against
# slowapi's module globals, where these types do not exist, so string
# annotations break dependency injection on every decorated route.
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import limiter, require_principal
from app.config.settings import Settings, get_settings
from app.db.session import get_db
from app.schemas.evaluation import (
    EvaluateTriadRequest,
    EvaluationResponse,
    QueryRequest,
)
from app.services.orchestrator import (
    PipelineInput,
    evaluate_supplied_triad,
    run_pipeline,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["evaluation"])


@router.post("/query", response_model=EvaluationResponse)
@limiter.limit("30/minute")
async def query(
    request: Request,
    payload: QueryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[str, Depends(require_principal)],
) -> EvaluationResponse:
    """Run a query through retrieval, generation and the full evaluation pipeline.

    Returns the complete trust report: the RAG triad, every score, the guardrail
    verdict, per-stage latency and a plain-language explanation of the outcome.
    """
    return await run_pipeline(
        PipelineInput(
            query=payload.query,
            top_k=payload.top_k,
            channel=payload.channel,
            reference_answer=payload.reference_answer,
        ),
        db=db,
        settings=settings,
    )


@router.post("/evaluate", response_model=EvaluationResponse)
@limiter.limit("30/minute")
async def evaluate(
    request: Request,
    payload: EvaluateTriadRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[str, Depends(require_principal)],
) -> EvaluationResponse:
    """Evaluate a Query/Context/Answer triad supplied directly.

    Retrieval and generation are skipped, so the result depends only on the
    evaluator. This is the endpoint the reliability test cases use, and it is
    how an external agent can submit its own interactions for scoring.
    """
    return await evaluate_supplied_triad(
        query=payload.query,
        contexts=payload.contexts,
        answer=payload.answer,
        reference_answer=payload.reference_answer,
        db=db,
        settings=settings,
    )
