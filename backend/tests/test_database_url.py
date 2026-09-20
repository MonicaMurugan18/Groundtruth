"""DATABASE_URL normalisation.

Managed Postgres hosts (Render, Heroku, Supabase, Neon) issue URLs this
application cannot consume unchanged. Both failures happen at startup, so they
are exactly the kind of thing that turns a deploy into a debugging session:

    postgres://...            -> NoSuchModuleError (no such SQLAlchemy dialect)
    postgresql://...          -> resolves to psycopg2 (sync, not installed)
    ...?sslmode=require       -> asyncpg: unexpected keyword argument 'sslmode'

These pin the translation so a pasted URL just works, and so SQLite - the local
development default - keeps working untouched.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.session import _normalise_postgres_url


@pytest.mark.parametrize(
    "supplied",
    [
        "postgres://user:pw@host:5432/db",
        "postgresql://user:pw@host:5432/db",
        "postgresql+asyncpg://user:pw@host:5432/db",
    ],
)
def test_every_postgres_url_shape_becomes_asyncpg(supplied: str):
    url, _ = _normalise_postgres_url(supplied)
    assert url.startswith("postgresql+asyncpg://")
    # The decisive check: SQLAlchemy can actually build an async engine from it.
    assert create_async_engine(url).dialect.driver == "asyncpg"


def test_credentials_and_database_survive_normalisation():
    url, _ = _normalise_postgres_url("postgres://user:pw@host:5432/mydb")
    assert url == "postgresql+asyncpg://user:pw@host:5432/mydb"


def test_sslmode_is_translated_to_an_asyncpg_connect_arg():
    """asyncpg rejects sslmode; it must be lifted out of the URL."""
    url, connect_args = _normalise_postgres_url(
        "postgres://user:pw@host:5432/db?sslmode=require"
    )
    assert "sslmode" not in url
    assert connect_args == {"ssl": True}


def test_sslmode_disable_does_not_request_tls():
    _, connect_args = _normalise_postgres_url(
        "postgres://user:pw@host/db?sslmode=disable"
    )
    assert connect_args == {}


def test_other_query_parameters_are_preserved():
    url, _ = _normalise_postgres_url(
        "postgres://user:pw@host/db?sslmode=require&application_name=groundtruth"
    )
    assert "application_name=groundtruth" in url


def test_sqlite_is_left_completely_alone():
    """Local development must not be affected by any of this."""
    supplied = "sqlite+aiosqlite:///./data/groundtruth.db"
    url, connect_args = _normalise_postgres_url(supplied)
    assert url == supplied
    assert connect_args == {}
