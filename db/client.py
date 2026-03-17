"""
SQLAlchemy database client for Supabase PostgreSQL.

Expects DATABASE_URL in environment (Supabase provides this in project settings).
Format: postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
"""

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Supabase uses standard PostgreSQL; async requires asyncpg driver (postgresql+asyncpg://)
# Sync uses psycopg2 (postgresql:// or postgresql+psycopg2://)


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Get it from Supabase Dashboard → Project Settings → Database."
        )
    
    # If DATABASE_URL is set to "sqlite", use local SQLite database
    if url == "sqlite":
        return "sqlite:///./localcode.db"
    
    return url


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
        _get_database_url(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        echo=os.environ.get("SQL_ECHO", "").lower() in ("1", "true"),
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
            _url_for_async(_get_database_url()),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            echo=os.environ.get("SQL_ECHO", "").lower() in ("1", "true"),
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
]
