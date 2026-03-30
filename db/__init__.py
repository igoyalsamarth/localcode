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
    """
    Create all application tables on PostgreSQL.

    Uses an advisory lock so parallel API/worker processes do not race on ``create_all`` —
    the failure mode is most visible on a **fresh empty database** (DDL / ENUM / ``pg_type``
    conflicts when every replica runs ``CREATE`` at once).
    """
    register_models()
    from sqlalchemy import text

    from db.pg_locks import PG_ADV_LOCK_SQLALCHEMY_CREATE_ALL

    engine = get_engine()
    if engine.dialect.name != "postgresql":
        raise RuntimeError(
            "create_tables() requires PostgreSQL (postgresql:// DATABASE_URL). "
            "Unit tests must patch db.get_engine with a PostgreSQL dialect mock."
        )

    with engine.connect() as conn:
        conn.execute(
            text("SELECT pg_advisory_lock(:k)"),
            {"k": PG_ADV_LOCK_SQLALCHEMY_CREATE_ALL},
        )
        try:
            Base.metadata.create_all(bind=conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.execute(
                text("SELECT pg_advisory_unlock(:k)"),
                {"k": PG_ADV_LOCK_SQLALCHEMY_CREATE_ALL},
            )
            conn.commit()


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
