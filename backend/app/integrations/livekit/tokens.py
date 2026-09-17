"""LiveKit access-token minting.

Tokens are always signed server-side. ``LIVEKIT_API_SECRET`` never leaves the
backend and is never sent to the browser - the frontend receives only a
short-lived, room-scoped JWT and the public ``LIVEKIT_URL``.

Grants are deliberately narrow: the participant may join exactly one room and
publish and subscribe to audio. Room creation and administrative rights are not
granted.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class LiveKitNotConfigured(RuntimeError):
    """Raised when LiveKit credentials are absent."""


@dataclass(slots=True)
class VoiceSession:
    server_url: str
    token: str
    room: str
    identity: str
    agent_name: str


def create_voice_session(
    *,
    identity: str | None = None,
    room: str | None = None,
    settings: Settings | None = None,
    ttl_minutes: int = 30,
) -> VoiceSession:
    """Mint a LiveKit token for a browser participant."""
    settings = settings or get_settings()
    if not settings.livekit_configured:
        raise LiveKitNotConfigured(
            "LiveKit is not configured. Set LIVEKIT_URL, LIVEKIT_API_KEY and "
            "LIVEKIT_API_SECRET in backend/.env to enable voice evaluation."
        )

    try:
        from livekit import api
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise LiveKitNotConfigured(
            "The 'livekit-api' package is not installed. Run: pip install livekit-api"
        ) from exc

    from datetime import timedelta

    participant_identity = identity or f"user-{uuid.uuid4().hex[:12]}"
    room_name = room or f"groundtruth-{uuid.uuid4().hex[:12]}"

    grants = api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
        # The browser participant publishes audio only; no data-channel writes.
        can_publish_data=False,
    )

    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(participant_identity)
        .with_name(participant_identity)
        .with_grants(grants)
        .with_ttl(timedelta(minutes=ttl_minutes))
        .to_jwt()
    )

    logger.info("Issued LiveKit token for %s in room %s", participant_identity, room_name)
    return VoiceSession(
        server_url=settings.livekit_url,
        token=token,
        room=room_name,
        identity=participant_identity,
        agent_name=settings.livekit_agent_name,
    )
