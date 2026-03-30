"""
SQLAlchemy database client for PostgreSQL.

Connection URL comes from ``constants.get_database_url()`` (``DATABASE_URL`` env).
Typical form: ``postgresql://USER:PASSWORD@HOST:5432/DATABASE``
(synchronous code uses psycopg2; see driver notes below).
"""

from contextlib import contextmanager
from typing import Generator

from constants import get_database_url, get_sql_echo
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Async SQLAlchemy uses asyncpg (postgresql+asyncpg:// after :func:`_url_for_async`).
# Sync uses psycopg2 (postgresql:// or postgresql+psycopg2://).


def get_psycopg_conninfo() -> str:
    """
    Normalized ``postgresql://`` URI for psycopg3 (same host/credentials as SQLAlchemy).

    Accepts ``postgresql://`` or the same host with ``+asyncpg`` / ``+psycopg2`` driver prefix.
    """
    url = get_database_url()
    for prefix in ("postgresql+psycopg2://", "postgresql+asyncpg://"):
        if url.startswith(prefix):
            rest = url.split("://", 1)[1]
            return f"postgresql://{rest}"
    if url.startswith("postgresql://"):
        return url
    raise RuntimeError(
        "DATABASE_URL must be a postgresql:// URI "
        "(optional +asyncpg or +psycopg2 driver prefix only)."
    )


def _url_for_async(url: str) -> str:
    """Convert postgresql:// to postgresql+asyncpg:// for async engine."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    return url


class Base(DeclarativeBase):
    """Base class for all declarative models."""

    pass


def _create_sync_engine() -> Engine:
    return create_engine(
        get_database_url(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        echo=get_sql_echo(),
    )


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_async_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> Engine:
    """Return the sync SQLAlchemy engine (creates on first call)."""
    global _engine
    if _engine is None:
        _engine = _create_sync_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the sync session factory (creates on first call)."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _SessionLocal


def get_async_engine() -> AsyncEngine:
    """Return the async SQLAlchemy engine (creates on first call)."""
    global _async_engine
    if _async_engine is None:
        _async_engine = create_async_engine(
            _url_for_async(get_database_url()),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            echo=get_sql_echo(),
        )
    return _async_engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the async session factory (creates on first call)."""
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        _AsyncSessionLocal = async_sessionmaker(
            bind=get_async_engine(),
            class_=AsyncSession,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _AsyncSessionLocal


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Context manager for sync sessions. Commits on success, rolls back on error."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Convenience: import Base and session_scope for defining models and running queries
__all__ = [
    "Base",
    "session_scope",
    "get_engine",
    "get_session_factory",
    "get_async_engine",
    "get_async_session_factory",
    "get_psycopg_conninfo",
]
