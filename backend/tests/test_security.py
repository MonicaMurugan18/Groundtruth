"""Security tests.

Covers the three places where a mistake would be quiet and expensive: the
production configuration guard, JWT handling, and upload filename sanitisation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.api.routes.ingest import _safe_filename
from app.api.security import (
    DEFAULT_SECRET,
    AuthError,
    assert_production_security,
    decode_token,
    issue_token,
)
from app.config.settings import Settings, get_settings


# --- Production configuration guard -----------------------------------------


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (
            dict(app_env="production", auth_disabled=True, jwt_secret_key="real-secret"),
            "AUTH_DISABLED",
        ),
        (
            dict(app_env="production", auth_disabled=False, jwt_secret_key=DEFAULT_SECRET),
            "JWT_SECRET_KEY",
        ),
        (
            dict(
                app_env="production",
                auth_disabled=False,
                jwt_secret_key="real-secret",
                cors_origins="*",
            ),
            "CORS_ORIGINS",
        ),
    ],
)
def test_production_refuses_insecure_configuration(kwargs: dict, expected: str):
    """An insecure production deployment must fail loudly at startup."""
    with pytest.raises(RuntimeError, match=expected):
        assert_production_security(Settings(**kwargs))


def test_production_accepts_a_secure_configuration():
    assert_production_security(
        Settings(
            app_env="production",
            auth_disabled=False,
            jwt_secret_key="a-properly-random-secret",
            cors_origins="https://groundtruth.example.com",
        )
    )


def test_development_defaults_are_allowed():
    """Insecure defaults are fine in development; the guard is production-only."""
    assert_production_security(
        Settings(app_env="development", auth_disabled=True, jwt_secret_key=DEFAULT_SECRET)
    )


# --- JWT --------------------------------------------------------------------


def test_token_round_trip_preserves_subject():
    token = issue_token("analyst@example.com")
    claims = decode_token(token)
    assert claims["sub"] == "analyst@example.com"
    assert claims["iss"] == "groundtruth"


def test_token_carries_extra_claims():
    token = issue_token("svc-agent", {"scope": "voice"})
    assert decode_token(token)["scope"] == "voice"


def test_expired_token_is_rejected():
    settings = get_settings()
    expired = jwt.encode(
        {
            "sub": "someone",
            "iss": "groundtruth",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(AuthError, match="expired"):
        decode_token(expired)


def test_token_signed_with_another_key_is_rejected():
    settings = get_settings()
    forged = jwt.encode(
        {
            "sub": "attacker",
            "iss": "groundtruth",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        # At least 32 bytes, so the assertion is about the signature mismatch
        # rather than a key-length warning from PyJWT.
        "a-completely-different-secret-of-sufficient-length",
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(AuthError, match="Invalid"):
        decode_token(forged)


def test_token_from_another_issuer_is_rejected():
    settings = get_settings()
    foreign = jwt.encode(
        {
            "sub": "someone",
            "iss": "some-other-service",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(AuthError):
        decode_token(foreign)


# --- Upload filename sanitisation -------------------------------------------


@pytest.mark.parametrize(
    "supplied",
    [
        "../../../etc/passwd",
        "..\\..\\windows\\system32\\config\\sam",
        "/absolute/path/secrets.txt",
        "C:\\Users\\hp\\.env",
    ],
)
def test_path_traversal_cannot_escape_the_upload_directory(supplied: str):
    """A crafted filename must reduce to a bare, safe basename."""
    safe = _safe_filename(supplied)
    assert "/" not in safe
    assert "\\" not in safe
    assert not safe.startswith(".")
    assert ".." not in safe


def test_sanitised_filename_keeps_a_usable_extension():
    assert _safe_filename("quarterly report.pdf") == "quarterly_report.pdf"


def test_empty_or_hostile_filename_falls_back_to_a_default():
    assert _safe_filename("...") == "document"
    assert _safe_filename("") == "document"


def test_filename_length_is_bounded():
    assert len(_safe_filename("a" * 500 + ".txt")) <= 200
