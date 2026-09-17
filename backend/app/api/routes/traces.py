"""Evaluation history and dashboard statistics."""

# NOTE: deliberately no `from __future__ import annotations` here.
# slowapi's @limiter.limit wrapper makes FastAPI resolve type hints against
# slowapi's module globals, where these types do not exist, so string
# annotations break dependency injection on every decorated route.
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import require_principal
from app.db.session import get_db
from app.schemas.common import ReliabilityStatus, SourceChannel
from app.schemas.evaluation import DashboardStats, EvaluationResponse, TraceSummary
from app.services import trace_store

router = APIRouter(tags=["traces"])


class TraceListResponse(BaseModel):
    items: list[TraceSummary]
    total: int
    limit: int
    offset: int


@router.get("/traces", response_model=TraceListResponse)
async def list_traces(
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[str, Depends(require_principal)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[ReliabilityStatus | None, Query(alias="status")] = None,
    channel: Annotated[SourceChannel | None, Query()] = None,
) -> TraceListResponse:
    """Paginated evaluation history for the history table."""
    items, total = await trace_store.list_traces(
        db,
        limit=limit,
        offset=offset,
        status=status_filter.value if status_filter else None,
        channel=channel.value if channel else None,
    )
    return TraceListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/traces/{evaluation_id}", response_model=EvaluationResponse)
async def get_trace(
    evaluation_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[str, Depends(require_principal)],
) -> EvaluationResponse:
    """The complete stored trace for one evaluation."""
    row = await trace_store.get_trace(db, evaluation_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No evaluation found with id {evaluation_id}.",
        )
    return trace_store.to_response(row)


@router.get("/stats", response_model=DashboardStats)
async def get_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[str, Depends(require_principal)],
    recent: Annotated[int, Query(ge=1, le=50)] = 10,
) -> DashboardStats:
    """Aggregate metrics for the dashboard landing page."""
    return await trace_store.get_stats(db, recent_limit=recent)
