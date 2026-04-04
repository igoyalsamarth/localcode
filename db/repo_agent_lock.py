"""Serialize GitHub deep-agent runs per repository (coder + reviewer) via PostgreSQL."""

from __future__ import annotations

import hashlib
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import text

from db.client import get_engine
from logger import get_logger

logger = get_logger(__name__)


def github_repo_agent_lock_key(github_repo_id: int) -> int:
    """Stable 64-bit advisory lock id for a GitHub ``repository.id``."""
    payload = f"greagent:github_repo_agent:{github_repo_id}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big", signed=True)


@contextmanager
def hold_github_repo_agent_lock(github_repo_id: int) -> Generator[None, None, None]:
    """
    Block until this repository's agent lock is acquired, then hold it for the whole run.

    Uses a session-level ``pg_advisory_lock`` on PostgreSQL; no-op on other dialects.

    The lock is held inside **one open transaction** on a dedicated connection (no
    ``COMMIT`` until after ``yield``). That matches **PgBouncer transaction pooling**
    (e.g. Supabase :6543): an intermediate commit would return the server to the pool and
    release the advisory lock while workers still assume it is held.
    """
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        yield
        return

    key = github_repo_agent_lock_key(github_repo_id)
    conn = engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": key})
        yield
    finally:
        try:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            trans.commit()
        except Exception:
            logger.exception(
                "Failed to release github repo agent lock (github_repo_id=%s)",
                github_repo_id,
            )
            trans.rollback()
        finally:
            conn.close()
