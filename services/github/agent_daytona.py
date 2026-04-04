"""
Daytona sandbox lifecycle for GitHub deep agents (issue + PR workflows).

See LangChain Deep Agents sandboxes:
https://docs.langchain.com/oss/python/deepagents/sandboxes#daytona
"""

from __future__ import annotations

from dataclasses import dataclass

from daytona import (
    CreateSandboxFromSnapshotParams,
    Daytona,
    DaytonaNotFoundError,
    Sandbox as DaytonaSandboxHandle,
)
from langchain_daytona import DaytonaSandbox

from constants import (
    daytona_sandbox_snapshot,
)
from logger import get_logger

logger = get_logger(__name__)


def _daytona_path(sandbox_home: str) -> str:
    """Ensure ``~/bin`` (for bundled ``gh``) is first on ``PATH``."""
    return f"{sandbox_home}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def build_sandbox_env_vars(
    gh_token: str,
    *,
    git_author: tuple[str, str] | None,
    git_committer: tuple[str, str] | None,
    repo_name: str,
) -> dict[str, str]:
    """
    Environment inside the sandbox for ``git`` / ``gh``.
    """
    rel = f"repos/{repo_name}"
    env: dict[str, str] = {
        "GH_TOKEN": gh_token,
        "HOME": "/root",
        "PATH": _daytona_path("/root"),
        "WORKFLOW_REPO_REL": rel,
        "WORKFLOW_REPO_ABS": f"/{rel}",
    }
    if git_author:
        an, ae = git_author
        cn, ce = git_committer if git_committer is not None else (an, ae)
        env["GIT_AUTHOR_NAME"] = an
        env["GIT_AUTHOR_EMAIL"] = ae
        env["GIT_COMMITTER_NAME"] = cn
        env["GIT_COMMITTER_EMAIL"] = ce
    return env


@dataclass
class DaytonaAgentSession:
    """Holds the Daytona client handle and sandbox for cleanup."""

    daytona: Daytona
    sandbox: DaytonaSandboxHandle


def create_daytona_agent_session(
    run_id: str,
    env_vars: dict[str, str],
    *,
    create_timeout_sec: float = 120,
) -> tuple[DaytonaSandbox, DaytonaAgentSession]:
    """
    Create an **ephemeral** sandbox and wrap it with :class:`DaytonaSandbox` for ``create_deep_agent``.

    ``ephemeral=True`` maps to immediate removal once the sandbox is stopped (see Daytona
    ``CreateSandboxBaseParams``). Always call :func:`stop_sandbox` after the agent run.

    Snapshot selection: set ``DAYTONA_SNAPSHOT`` to a Daytona-registered snapshot name
    (e.g. minimal git+gh GHCR image). Otherwise uses Daytona's stock snapshot for
    """
    client = Daytona()
    snap = daytona_sandbox_snapshot()
    params = CreateSandboxFromSnapshotParams(
        snapshot=snap,
        env_vars=env_vars,
        labels={"run_id": run_id, "app": "greagent-github-deep-agent"},
        ephemeral=True,
    )
    sandbox = client.create(params, timeout=create_timeout_sec)
    backend = DaytonaSandbox(sandbox=sandbox, timeout=30 * 60)
    return backend, DaytonaAgentSession(daytona=client, sandbox=sandbox)


def stop_sandbox(session: DaytonaAgentSession | None) -> None:
    """
    Stop the sandbox. For ephemeral sandboxes (``auto_delete_interval=0``), Daytona
    deletes the sandbox as soon as it is stopped—no separate delete call.

    If ``stop()`` fails (e.g. timeout or API error), call ``delete()`` so the runner
    does not leave a started sandbox behind.
    """
    if session is None:
        return
    sandbox_id = session.sandbox.id
    stop_timeout = 120.0
    try:
        session.sandbox.stop(timeout=stop_timeout)
    except DaytonaNotFoundError:
        return
    except Exception:
        logger.exception(
            "Failed to stop Daytona sandbox id=%s; attempting delete",
            sandbox_id,
        )
        try:
            session.sandbox.delete(timeout=stop_timeout)
        except DaytonaNotFoundError:
            return
        except Exception:
            logger.exception(
                "Failed to delete Daytona sandbox id=%s after stop failure",
                sandbox_id,
            )
