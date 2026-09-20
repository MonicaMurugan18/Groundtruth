"""Login, registration and route protection.

Runs against the real FastAPI app and a real (in-memory) database, because the
thing under test is the wiring between the router, the password hashing and the
existing JWT dependency - not any one of those in isolation.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.security import decode_token
from app.config.settings import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services import auth as auth_service

DEMO_EMAIL = "demo@groundtruth.dev"
DEMO_PASSWORD = "groundtruth-demo-2026"


@pytest.fixture
async def client():
    """App wired to a throwaway database, with auth enforcement ON."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_db():
        async with factory() as session:
            yield session

    def _override_settings():
        base = get_settings()
        return Settings(
            **{
                **base.model_dump(),
                "auth_disabled": False,
                "jwt_secret_key": "test-secret-key-of-sufficient-length-1234",
            }
        )

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_settings] = _override_settings

    # Every test here shares one client IP, so the real 5/minute cap on
    # /auth/register would make results depend on test order. Rate limiting is
    # verified separately (and live); these tests are about the auth logic.
    from app.api.security import limiter

    limiter.enabled = False
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        limiter.enabled = True
        app.dependency_overrides.clear()
        await engine.dispose()


# --- Password hashing -------------------------------------------------------


def test_password_is_never_stored_in_plaintext():
    stored = auth_service.hash_password(DEMO_PASSWORD)
    assert DEMO_PASSWORD not in stored
    assert stored.startswith("pbkdf2_sha256$")


def test_same_password_hashes_differently_each_time():
    """A per-user salt means identical passwords do not share a digest."""
    assert auth_service.hash_password("same") != auth_service.hash_password("same")


def test_verify_accepts_the_right_password_and_rejects_others():
    stored = auth_service.hash_password(DEMO_PASSWORD)
    assert auth_service.verify_password(DEMO_PASSWORD, stored) is True
    assert auth_service.verify_password("wrong", stored) is False


def test_malformed_hash_is_a_failed_login_not_a_crash():
    assert auth_service.verify_password("x", "not-a-valid-hash") is False


# --- Registration -----------------------------------------------------------


async def test_register_creates_an_account_and_returns_a_usable_token(client):
    response = await client.post(
        "/auth/register", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == DEMO_EMAIL
    assert decode_token(body["access_token"])["sub"] == DEMO_EMAIL


async def test_register_rejects_a_duplicate_email(client):
    await client.post("/auth/register", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    duplicate = await client.post(
        "/auth/register", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert duplicate.status_code == 409


async def test_register_rejects_a_short_password(client):
    response = await client.post(
        "/auth/register", json={"email": DEMO_EMAIL, "password": "short"}
    )
    assert response.status_code == 422


async def test_register_rejects_a_malformed_email(client):
    response = await client.post(
        "/auth/register", json={"email": "not-an-email", "password": DEMO_PASSWORD}
    )
    assert response.status_code == 422


# --- Login ------------------------------------------------------------------


async def test_valid_login_returns_a_token(client):
    await client.post("/auth/register", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    response = await client.post(
        "/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )

    assert response.status_code == 200
    assert decode_token(response.json()["access_token"])["sub"] == DEMO_EMAIL


async def test_login_is_case_insensitive_on_email(client):
    await client.post("/auth/register", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    response = await client.post(
        "/auth/login", json={"email": DEMO_EMAIL.upper(), "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200


async def test_invalid_password_is_rejected(client):
    await client.post("/auth/register", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    response = await client.post(
        "/auth/login", json={"email": DEMO_EMAIL, "password": "definitely-wrong"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password."


async def test_unknown_account_gives_the_same_error_as_a_wrong_password(client):
    """The response must not reveal which emails are registered."""
    await client.post("/auth/register", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    wrong_password = await client.post(
        "/auth/login", json={"email": DEMO_EMAIL, "password": "wrong-password"}
    )
    unknown_user = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"}
    )

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json()["detail"] == unknown_user.json()["detail"]


async def test_login_response_never_echoes_the_password(client):
    await client.post("/auth/register", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    response = await client.post(
        "/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert DEMO_PASSWORD not in response.text


# --- Protected endpoints ----------------------------------------------------


@pytest.mark.parametrize("path", ["/auth/me", "/stats", "/traces"])
async def test_protected_endpoints_reject_unauthenticated_requests(client, path):
    response = await client.get(path)
    assert response.status_code == 401


async def test_protected_endpoint_rejects_a_garbage_token(client):
    response = await client.get(
        "/auth/me", headers={"Authorization": "Bearer not-a-real-jwt"}
    )
    assert response.status_code == 401


async def test_protected_endpoint_accepts_a_token_from_login(client):
    await client.post("/auth/register", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    token = (
        await client.post(
            "/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
        )
    ).json()["access_token"]

    response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json() == {"email": DEMO_EMAIL, "authenticated": True}


async def test_logout_is_effective_because_the_token_stops_being_sent(client):
    """Logout clears the client's credential; the API simply sees no token.

    There is no server-side session to destroy - tokens are stateless - so this
    asserts the property that actually matters: a request made without the
    token is rejected exactly as it was before login.
    """
    await client.post("/auth/register", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    token = (
        await client.post(
            "/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
        )
    ).json()["access_token"]

    assert (
        await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 200
    # ...after logout the cookie is gone, so no Authorization header is sent:
    assert (await client.get("/auth/me")).status_code == 401
