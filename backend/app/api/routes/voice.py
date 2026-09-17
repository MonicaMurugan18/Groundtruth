"""LiveKit voice endpoints.

Two responsibilities:

* Mint a room-scoped LiveKit token for the browser. The API secret stays on the
  server; the client receives only a short-lived JWT.
* Accept evaluated turns from the voice agent. The agent posts each completed
  turn here, so a spoken interaction lands in exactly the same evaluation
  pipeline and trace store as a typed one, and shows up on the dashboard
  labelled ``channel=voice``.
"""

# NOTE: deliberately no `from __future__ import annotations` here.
# slowapi's @limiter.limit wrapper makes FastAPI resolve type hints against
# slowapi's module globals, where these types do not exist, so string
# annotations break dependency injection on every decorated route.
import logging
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import limiter, require_principal
from app.config.settings import Settings, get_settings
from app.db.session import get_db
from app.integrations.livekit.tokens import LiveKitNotConfigured, create_voice_session
from app.schemas.common import SourceChannel
from app.schemas.evaluation import EvaluationResponse
from app.services.orchestrator import (
    PipelineInput,
    evaluate_supplied_triad,
    run_pipeline,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])


class VoiceTokenResponse(BaseModel):
    server_url: str
    token: str
    room: str
    identity: str
    agent_name: str


class VoiceTurnRequest(BaseModel):
    """One completed spoken turn submitted by the LiveKit agent."""

    query: str = Field(min_length=1, max_length=4000, description="Transcribed user speech.")
    answer: str | None = Field(
        default=None,
        max_length=8000,
        description=(
            "The agent's spoken reply. When omitted, Groundtruth runs its own "
            "retrieval and generation for the transcript instead."
        ),
    )
    contexts: list[str] | None = Field(
        default=None,
        max_length=50,
        description="Context the voice agent actually retrieved, if it retrieved its own.",
    )


@router.get("/token", response_model=VoiceTokenResponse)
@limiter.limit("20/minute")
async def voice_token(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[str, Depends(require_principal)],
) -> VoiceTokenResponse:
    """Issue a LiveKit token so the browser can join a voice room."""
    try:
        session = create_voice_session(settings=settings)
    except LiveKitNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    return VoiceTokenResponse(**asdict(session))


@router.post("/turn", response_model=EvaluationResponse)
@limiter.limit("60/minute")
async def evaluate_voice_turn(
    request: Request,
    payload: VoiceTurnRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[str, Depends(require_principal)],
) -> EvaluationResponse:
    """Evaluate one spoken turn and record it as a voice trace.

    If the agent supplies both its retrieved context and its answer, that exact
    triad is evaluated - which is what makes the voice trace a faithful record of
    what the user actually heard. Otherwise Groundtruth runs the transcript
    through its own pipeline.
    """
    if payload.answer and payload.contexts:
        return await evaluate_supplied_triad(
            query=payload.query,
            contexts=payload.contexts,
            answer=payload.answer,
            db=db,
            channel=SourceChannel.VOICE,
            settings=settings,
        )

    return await run_pipeline(
        PipelineInput(query=payload.query, channel=SourceChannel.VOICE),
        db=db,
        settings=settings,
    )
