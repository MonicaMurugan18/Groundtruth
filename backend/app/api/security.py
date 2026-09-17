"""Authentication and rate limiting.

The architecture calls for an OAuth2/JWT gateway. This module implements the
JWT half and is deliberately shaped so an OAuth2 provider can be dropped in by
replacing :func:`issue_token` without touching any route.

During development ``AUTH_DISABLED=true`` lets the dashboard call the API without
a token. That default flips automatically in production: if ``APP_ENV`` is
production the API refuses to start with auth disabled or with a default secret,
so an insecure deployment fails loudly instead of silently.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

DEFAULT_SECRET = "dev-only-insecure-secret-change-me"

# Rate limiting is keyed on client IP. Behind a proxy, configure the proxy to
# set X-Forwarded-For and switch this to a header-aware key function.
limiter = Limiter(key_func=get_remote_address)

# auto_error=False so we can honour AUTH_DISABLED rather than rejecting outright.
_bearer = HTTPBearer(auto_error=False)


class AuthError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


def issue_token(subject: str, extra_claims: dict[str, Any] | None = None) -> str:
    """Mint a Groundtruth API token for ``subject``."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
        "iss": "groundtruth",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer="groundtruth",
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid authentication token.") from exc


async def require_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    """Resolve the calling principal, or raise 401.

    Returns the literal ``"anonymous"`` when auth is disabled, so downstream code
    always has a principal to attribute a trace to.
    """
    if settings.auth_disabled:
        return "anonymous"
    if credentials is None:
        raise AuthError("Missing bearer token.")
    claims = decode_token(credentials.credentials)
    subject = claims.get("sub")
    if not subject:
        raise AuthError("Token is missing a subject claim.")
    return str(subject)


def assert_production_security(settings: Settings) -> None:
    """Refuse to run an insecure configuration in production."""
    if not settings.is_production:
        return
    problems: list[str] = []
    if settings.auth_disabled:
        problems.append("AUTH_DISABLED must be false in production")
    if settings.jwt_secret_key == DEFAULT_SECRET:
        problems.append("JWT_SECRET_KEY is still the default value")
    if "*" in settings.cors_origin_list:
        problems.append("CORS_ORIGINS must not be '*' in production")
    if problems:
        raise RuntimeError("Insecure production configuration: " + "; ".join(problems))
