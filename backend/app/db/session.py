"""Async SQLAlchemy engine and session management.

The trace store is PostgreSQL. A SQLite URL is accepted so the stack can be run
without Docker during development; the schema is identical because every column
type used is portable.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import BACKEND_DIR, get_settings
from app.db.base import Base

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _normalise_sqlite_path(url: str) -> str:
    """Anchor a relative SQLite path to ``backend/`` and ensure its directory.

    Without this, the database file lands wherever uvicorn happened to be
    started from, which silently splits traces across multiple files.
    """
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        return url
    raw = url[len(prefix) :]
    if raw.startswith("/"):  # already absolute
        return url
    resolved = (BACKEND_DIR / raw).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{resolved.as_posix()}"


def _normalise_postgres_url(url: str) -> tuple[str, dict]:
    """Accept the DATABASE_URL shapes managed hosts actually hand out.

    Render, Heroku, Supabase and Neon issue URLs this application cannot use
    unchanged, and both failures happen at startup:

    * ``postgres://``   -> SQLAlchemy 2 has no such dialect (NoSuchModuleError)
    * ``postgresql://`` -> resolves to psycopg2, which is sync and not installed
    * ``?sslmode=require`` -> asyncpg rejects it (``connect() got an unexpected
      keyword argument 'sslmode'``); asyncpg spells it ``ssl``.

    Rather than make every operator hand-edit the URL, normalise it here and
    return any connect args the translation implies. SQLite is untouched.
    """
    connect_args: dict = {}
    if url.startswith("sqlite"):
        return url, connect_args

    # Scheme: force the async driver.
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]

    # Query string: translate sslmode -> asyncpg's ssl connect arg.
    if "sslmode=" in url:
        from urllib.parse import urlencode, urlsplit, urlunsplit

        parts = urlsplit(url)
        params = [
            (key, value)
            for key, value in (
                pair.split("=", 1) if "=" in pair else (pair, "")
                for pair in parts.query.split("&")
                if pair
            )
        ]
        sslmode = next((v for k, v in params if k == "sslmode"), None)
        remaining = [(k, v) for k, v in params if k != "sslmode"]
        url = urlunsplit(parts._replace(query=urlencode(remaining)))
        # disable/allow mean "no TLS"; everything else means "use TLS".
        if sslmode and sslmode not in {"disable", "allow"}:
            connect_args["ssl"] = True

    return url, connect_args


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine
    if _engine is None:
        settings = get_settings()
        url = _normalise_sqlite_path(settings.database_url)
        url, connect_args = _normalise_postgres_url(url)
        _engine = create_async_engine(
            url,
            echo=False,
            pool_pre_ping=True,
            future=True,
            connect_args=connect_args,
        )
        logger.info(
            "Database engine created (%s%s)",
            url.split("://", 1)[0],
            ", TLS" if connect_args.get("ssl") else "",
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a session that rolls back on error."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def _detect_schema_drift(connection) -> dict[str, list[str]]:
    """Return columns the models declare that the live tables are missing.

    ``create_all`` creates missing *tables* but never alters existing ones, so a
    new column on an existing table leaves the database silently behind. Every
    read then fails with an opaque "no such column" error at query time. This
    surfaces the problem at startup with an actionable message instead.
    """
    from sqlalchemy import inspect

    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    drift: dict[str, list[str]] = {}
    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            continue  # create_all handles a wholly missing table
        live_columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing = [c.name for c in table.columns if c.name not in live_columns]
        if missing:
            drift[table_name] = missing
    return drift


async def init_db() -> None:
    """Create tables if they do not exist, and warn loudly on schema drift.

    Adequate for a hackathon build; a production deployment would run Alembic
    migrations here instead.
    """
    # Imported for the side effect of registering models on Base.metadata.
    from app import models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        drift = await conn.run_sync(_detect_schema_drift)

    if drift:
        details = "; ".join(
            f"{table} is missing {', '.join(columns)}" for table, columns in drift.items()
        )
        logger.error(
            "DATABASE SCHEMA IS OUT OF DATE: %s. create_all cannot add columns to an "
            "existing table, so reads of these tables will fail. In development, "
            "delete the database and let it be recreated (SQLite: remove "
            "backend/data/groundtruth.db; Postgres: docker compose down -v). "
            "For a deployment that must keep its data, add a migration.",
            details,
        )
    else:
        logger.info("Database schema ready")


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
