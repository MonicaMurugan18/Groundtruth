"""Health and capability reporting.

``/health/capabilities`` is the honesty endpoint: it states exactly which
integrations are configured and reachable. The dashboard reads it so the UI can
say "Moss not configured" rather than quietly degrading to another backend and
presenting the result as though Moss produced it.
"""

# NOTE: deliberately no `from __future__ import annotations` here.
# slowapi's @limiter.limit wrapper makes FastAPI resolve type hints against
# slowapi's module globals, where these types do not exist, so string
# annotations break dependency injection on every decorated route.
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.db.session import get_db

router = APIRouter(tags=["health"])


class ComponentStatus(BaseModel):
    name: str
    configured: bool
    detail: str


class HealthResponse(BaseModel):
    status: str
    environment: str


class CapabilitiesResponse(BaseModel):
    components: list[ComponentStatus]
    degraded: list[str]


@router.get("/health", response_model=HealthResponse)
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Liveness probe."""
    return HealthResponse(status="ok", environment=settings.app_env)


@router.get("/health/capabilities", response_model=CapabilitiesResponse)
async def capabilities(
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CapabilitiesResponse:
    """Report which integrations are actually usable right now."""
    components: list[ComponentStatus] = []

    # Database — actually execute a statement rather than trusting the URL.
    try:
        await db.execute(text("SELECT 1"))
        db_ok, db_detail = True, f"Connected ({settings.database_url.split('://', 1)[0]})"
    except Exception as exc:  # pragma: no cover - depends on local infra
        db_ok, db_detail = False, f"Unreachable: {type(exc).__name__}"
    components.append(ComponentStatus(name="database", configured=db_ok, detail=db_detail))

    components.append(
        ComponentStatus(
            name="llm",
            configured=settings.llm_configured,
            detail=(
                f"OpenAI model {settings.llm_model}"
                if settings.llm_configured
                else "OPENAI_API_KEY is not set. Generation and RAGAS scoring are unavailable."
            ),
        )
    )
    components.append(
        ComponentStatus(
            name="moss",
            configured=settings.moss_configured,
            detail=(
                f"Index {settings.moss_index_name!r} (model {settings.moss_model_id})"
                if settings.moss_configured
                else "MOSS_PROJECT_ID / MOSS_PROJECT_KEY are not set."
            ),
        )
    )
    components.append(
        ComponentStatus(
            name="livekit",
            configured=settings.livekit_configured,
            detail=(
                f"Room server {settings.livekit_url}"
                if settings.livekit_configured
                else "LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET are not set."
            ),
        )
    )
    components.append(
        ComponentStatus(
            name="faiss",
            configured=settings.faiss_path.exists(),
            detail=f"Index directory {settings.faiss_path}",
        )
    )

    degraded = [component.name for component in components if not component.configured]
    return CapabilitiesResponse(components=components, degraded=degraded)
