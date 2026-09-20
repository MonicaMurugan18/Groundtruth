"""User accounts for the login flow.

Deliberately minimal: an identity to attach a JWT subject to. Roles, profiles
and password resets are out of scope - the existing ``app.api.security`` module
already owns token issuing and verification, and this adds only the account
record those tokens are issued *for*.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    """A login account.

    ``password_hash`` holds a salted PBKDF2 digest, never a plaintext password
    and never a reversible encoding. See ``app.services.auth``.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
