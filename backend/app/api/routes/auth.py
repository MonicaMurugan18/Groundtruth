"""Login and registration.

These endpoints mint tokens using the *existing* ``app.api.security`` machinery
(``issue_token`` / ``require_principal``). No second auth system is introduced:
this only adds the account records and the two endpoints that were missing.
"""

# NOTE: deliberately no `from __future__ import annotations` here.
# slowapi's @limiter.limit wrapper makes FastAPI resolve type hints against
# slowapi's module globals, where these types do not exist, so string
# annotations break dependency injection on every decorated route.
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import issue_token, limiter, require_principal
from app.config.settings import Settings, get_settings
from app.db.session import get_db
from app.services import auth as auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    email: EmailStr
    # Minimum length is enforced here so a weak password cannot be created at
    # all; the login route reuses the same model but only ever compares.
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    email: str


class MeResponse(BaseModel):
    email: str
    authenticated: bool


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request,
    payload: Credentials,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Create an account and return a token for it."""
    existing = await auth_service.get_user_by_email(db, payload.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )

    user = await auth_service.create_user(db, payload.email, payload.password)
    return TokenResponse(
        access_token=issue_token(user.email),
        expires_in_minutes=settings.jwt_expire_minutes,
        email=user.email,
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    payload: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Exchange credentials for a JWT."""
    user = await auth_service.authenticate(db, payload.email, payload.password)
    if user is None:
        # One message for both "no such account" and "wrong password", so the
        # response cannot be used to enumerate which emails are registered.
        logger.info("Failed login attempt for %s", auth_service.normalise_email(payload.email))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    return TokenResponse(
        access_token=issue_token(user.email),
        expires_in_minutes=settings.jwt_expire_minutes,
        email=user.email,
    )


@router.get("/me", response_model=MeResponse)
async def me(principal: Annotated[str, Depends(require_principal)]) -> MeResponse:
    """Who the current token belongs to. 401 when the token is missing/invalid."""
    return MeResponse(email=principal, authenticated=True)
