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

    Lock, DDL, and unlock run in **one transaction** on one connection so **PgBouncer
    transaction pooling** (e.g. Supabase pooler port ``6543``) does not return the server
    between statements and drop session-level advisory locks.
    """
    register_models()
    from sqlalchemy import text

    from logger import get_logger
    from db.pg_locks import PG_ADV_LOCK_SQLALCHEMY_CREATE_ALL

    log = get_logger(__name__)
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        raise RuntimeError(
            "create_tables() requires PostgreSQL (postgresql:// DATABASE_URL)."
        )

    conn = engine.connect()
    try:
        with conn.begin():
            conn.execute(
                text("SELECT pg_advisory_lock(:k)"),
                {"k": PG_ADV_LOCK_SQLALCHEMY_CREATE_ALL},
            )
            Base.metadata.create_all(bind=conn)
            conn.execute(
                text("SELECT pg_advisory_unlock(:k)"),
                {"k": PG_ADV_LOCK_SQLALCHEMY_CREATE_ALL},
            )
    except BaseException:
        try:
            with conn.begin():
                conn.execute(
                    text("SELECT pg_advisory_unlock(:k)"),
                    {"k": PG_ADV_LOCK_SQLALCHEMY_CREATE_ALL},
                )
        except Exception:
            log.exception(
                "Could not release create_tables advisory lock after failure "
                "(check DB connectivity; with transaction poolers prefer session mode if issues persist)"
            )
        raise
    finally:
        conn.close()


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
