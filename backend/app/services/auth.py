"""Password hashing and account lookup.

Hashing uses PBKDF2-HMAC-SHA256 from the standard library rather than pulling in
bcrypt or argon2. That is a deliberate trade: PBKDF2-HMAC-SHA256 at 600k
iterations is an OWASP-recommended configuration, it needs no new dependency or
native build on Windows, and the stored format is versioned so the algorithm can
be swapped later without invalidating existing rows.

Token issuing and verification are **not** here - they already exist in
``app.api.security`` and are reused unchanged, so there is exactly one
authentication system.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

logger = logging.getLogger(__name__)

# Stored as: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 600_000
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Return a salted, iterated digest. The plaintext is never stored."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGORITHM}${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Check a password against a stored digest in constant time."""
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != _ALGORITHM:
            return False
        expected = bytes.fromhex(digest_hex)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, AttributeError):
        # Malformed hash: treat as a failed login rather than a crash.
        return False
    # compare_digest avoids leaking match length through timing.
    return hmac.compare_digest(candidate, expected)


def normalise_email(email: str) -> str:
    return email.strip().lower()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == normalise_email(email)))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, email: str, password: str) -> User:
    """Create an account. Caller must have checked the email is free."""
    user = User(email=normalise_email(email), password_hash=hash_password(password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("Created user account %s", user.email)
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    """Return the user when the credentials are valid, else None.

    A missing account still runs a hash comparison so that "no such user" and
    "wrong password" take similar time and cannot be distinguished by timing.
    """
    user = await get_user_by_email(db, email)
    if user is None:
        verify_password(password, hash_password("dummy-password-for-timing"))
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
