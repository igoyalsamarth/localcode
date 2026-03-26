"""Database client and utilities."""

from constants import get_database_url
from db.client import (
    Base,
    get_async_engine,
    get_async_session_factory,
    get_engine,
    get_psycopg_conninfo,
    get_session_factory,
    session_scope,
)


def register_models() -> None:
    """Import all ORM models so Base.metadata includes them for create_all."""
    import model.tables  # noqa: F401


def create_tables() -> None:
    """Create all tables. Call register_models() first if using outside server context."""
    register_models()
    from db.client import get_engine

    Base.metadata.create_all(bind=get_engine())


__all__ = [
    "Base",
    "session_scope",
    "get_engine",
    "get_session_factory",
    "get_async_engine",
    "get_async_session_factory",
    "get_database_url",
    "get_psycopg_conninfo",
    "register_models",
    "create_tables",
]
