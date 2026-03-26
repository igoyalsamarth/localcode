"""
LangGraph checkpointing for the deep agent (PostgreSQL only).

Uses :class:`~langgraph.checkpoint.postgres.PostgresSaver` with a ``psycopg`` connection
pool. Checkpoint tables live in the **same database** as the app ORM (separate tables,
managed by LangGraph migrations via ``setup()``).

Persistence model (threads, ``thread_id``, checkpoints) is documented at:
https://docs.langchain.com/oss/python/langgraph/persistence

Production checkpointer reference:
https://docs.langchain.com/oss/python/langgraph/add-memory#example-using-postgres-checkpointer
"""

from __future__ import annotations

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Checkpointer
from logger import get_logger
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from db.client import get_psycopg_conninfo

logger = get_logger(__name__)

_checkpointer: Checkpointer | None = None
_pool: ConnectionPool | None = None


def init_checkpointer() -> Checkpointer:
    """
    Create the Postgres checkpointer and run LangGraph DB migrations once.

    Per LangGraph docs, ``PostgresSaver.setup()`` must be called the first time the
    checkpointer is used (creates ``checkpoints``, ``checkpoint_blobs``, etc.).

    Safe to call multiple times; returns the same instance after the first call.
    """
    global _checkpointer, _pool

    if _checkpointer is not None:
        return _checkpointer

    conninfo = get_psycopg_conninfo()

    # Migrations use CREATE INDEX CONCURRENTLY — must not run inside a transaction.
    # LangGraph's pool path uses implicit transactions; use autocommit for setup only.
    with Connection.connect(
        conninfo,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    ) as setup_conn:
        PostgresSaver(setup_conn).setup()

    _pool = ConnectionPool(
        conninfo=conninfo,
        open=True,
        max_size=20,
    )
    _checkpointer = PostgresSaver(_pool)
    _checkpointer.setup()
    logger.info(
        "LangGraph PostgresSaver initialized (checkpoint tables ensured in same DB as app)."
    )
    return _checkpointer


def get_checkpointer() -> Checkpointer:
    """Return the singleton checkpointer, initializing on first use."""
    return init_checkpointer()


def shutdown_checkpointer() -> None:
    """Close the psycopg pool on app shutdown."""
    global _checkpointer, _pool
    if _pool is not None:
        try:
            _pool.close()
        except Exception:
            logger.exception("Error closing LangGraph checkpoint pool")
        _pool = None
    _checkpointer = None


def github_issue_workflow_thread_id(full_name: str, issue_number: int) -> str:
    """
    Stable ``thread_id`` for issue-coding runs (``config["configurable"]["thread_id"]``).

    The checkpointer keys state by ``thread_id``; reuse the same id to resume or
    inspect state via ``graph.get_state`` / ``get_state_history`` (see persistence docs).
    """
    return f"github:{full_name}#issue-{issue_number}"


def github_pr_workflow_thread_id(full_name: str, pr_number: int) -> str:
    """Stable ``thread_id`` for PR review deep-agent runs."""
    return f"github:{full_name}#pr-{pr_number}"
