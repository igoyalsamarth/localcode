"""
Daytona sandbox lifecycle for GitHub deep agents (issue + PR workflows).

See LangChain Deep Agents sandboxes:
https://docs.langchain.com/oss/python/deepagents/sandboxes#daytona

Uses Daytona's stock snapshot (see ``language=`` in :func:`create_daytona_agent_session`).
If ``gh`` is missing, we install it into the sandbox user's ``~/bin`` after create (POSIX
``sh``-safe script; no bash-only ``pipefail``).
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from daytona import (
    CreateSandboxFromSnapshotParams,
    Daytona,
    DaytonaNotFoundError,
    Sandbox as DaytonaSandboxHandle,
)
from langchain_daytona import DaytonaSandbox

from constants import GITHUB_CLI_VERSION, daytona_sandbox_home
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
    sandbox_home: str | None = None,
) -> dict[str, str]:
    """
    Environment inside the sandbox for ``git`` / ``gh``.

    Sets ``WORKFLOW_REPO_ABS`` / ``WORKFLOW_REPO_REL`` so the model can resolve the clone
    location without guessing ``/repo`` vs ``/home/...``.
    """
    home = sandbox_home or daytona_sandbox_home()
    rel = f"repos/{repo_name}"
    env: dict[str, str] = {
        "GH_TOKEN": gh_token,
        "PATH": _daytona_path(home),
        "WORKFLOW_REPO_REL": rel,
        "WORKFLOW_REPO_ABS": f"{home}/{rel}",
    }
    if git_author:
        an, ae = git_author
        cn, ce = git_committer if git_committer is not None else (an, ae)
        env["GIT_AUTHOR_NAME"] = an
        env["GIT_AUTHOR_EMAIL"] = ae
        env["GIT_COMMITTER_NAME"] = cn
        env["GIT_COMMITTER_EMAIL"] = ce
    return env


def _exec_sh(
    sandbox: DaytonaSandboxHandle,
    script: str,
    *,
    timeout: int,
    env: dict[str, str] | None = None,
) -> object:
    """Run a script under POSIX ``sh`` (Daytona wraps ``process.exec`` with ``sh -c``)."""
    return sandbox.process.exec(script.strip(), env=env, timeout=timeout)


def ensure_github_cli_installed(
    sandbox: DaytonaSandboxHandle,
    *,
    sandbox_home: str,
    path_for_check: str,
) -> None:
    """
    Install the ``gh`` binary into ``<sandbox_home>/bin`` when missing.

    Daytona runs commands via ``sh`` (often dash): **do not use bash-only options** like
    ``pipefail``. Set ``DAYTONA_INSTALL_GH_CLI=false`` to skip when ``gh`` is preinstalled.

    ``path_for_check`` is the ``PATH`` used to detect an existing ``gh`` (defaults to
    ``_daytona_path(sandbox_home)``).
    """
    home = sandbox_home
    bin_dir = f"{home}/bin"
    check_path = path_for_check
    check = sandbox.process.exec(
        "command -v gh >/dev/null 2>&1",
        env={"PATH": check_path},
        timeout=60,
    )
    if check.exit_code == 0:
        return
    ver = GITHUB_CLI_VERSION.strip() or "2.88.1"
    # POSIX ``sh`` only (no ``pipefail``); explicit PATH so curl/tar resolve on minimal images.
    script = f"""
set -eu
BIN={shlex.quote(bin_dir)}
mkdir -p "$BIN"
arch=$(uname -m)
case "$arch" in
  x86_64) arch=amd64 ;;
  aarch64|arm64) arch=arm64 ;;
  *) echo "unsupported arch: $arch" >&2; exit 1 ;;
esac
rm -f /tmp/gh.tgz
curl -fsSL "https://github.com/cli/cli/releases/download/v{ver}/gh_{ver}_linux_$arch.tar.gz" -o /tmp/gh.tgz
tar -xzf /tmp/gh.tgz -C /tmp
ROOT="/tmp/gh_{ver}_linux_$arch"
cp "$ROOT/bin/gh" "$BIN/gh"
chmod +x "$BIN/gh"
rm -f /tmp/gh.tgz
"$BIN/gh" version
"""
    exec_env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    }
    try:
        r = _exec_sh(sandbox, script, timeout=180, env=exec_env)
        if r.exit_code != 0:
            logger.warning(
                "Could not install GitHub CLI in sandbox (exit=%s): %s",
                r.exit_code,
                (r.result or "")[:500],
            )
        else:
            logger.info("GitHub CLI (gh) installed in sandbox at %s/gh", bin_dir)
    except Exception:
        logger.exception(
            "GitHub CLI install failed; agent may fall back to curl for GitHub API"
        )


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

    Uses the TypeScript default snapshot so Node/npm/git tooling matches agent prompts.
    """
    client = Daytona()
    params = CreateSandboxFromSnapshotParams(
        language="typescript",
        env_vars=env_vars,
        labels={"run_id": run_id, "app": "greagent-github-deep-agent"},
        ephemeral=True,
    )
    sandbox = client.create(params, timeout=create_timeout_sec)
    home = sandbox.get_user_home_dir()
    ensure_github_cli_installed(
        sandbox,
        sandbox_home=home,
        path_for_check=_daytona_path(home),
    )
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
