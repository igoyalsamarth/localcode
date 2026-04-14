"""
Daytona sandbox lifecycle for GitHub deep agents (issue + PR workflows).

See LangChain Deep Agents sandboxes:
https://docs.langchain.com/oss/python/deepagents/sandboxes#daytona

Uses Daytona's TypeScript stock snapshot unless overridden (see :func:`create_daytona_agent_session`).
When :data:`~constants.DAYTONA_INSTALL_GH_CLI` is enabled and ``gh`` is missing, we install into
``<sandbox home>/bin`` after create (POSIX ``sh``-safe script; no bash-only ``pipefail``).
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

from constants import (
    DAYTONA_CODER_MAX_MINUTES,
    DAYTONA_CODER_WALL_CLOCK_SEC,
    DAYTONA_INSTALL_GH_CLI,
    GITHUB_CLI_VERSION,
    daytona_sandbox_home,
)
from logger import get_logger

logger = get_logger(__name__)


def _install_gh_cli_enabled() -> bool:
    v = DAYTONA_INSTALL_GH_CLI.strip().lower()
    return v not in ("0", "false", "no", "off", "")


# Typical Linux FHS PATH; ``_daytona_path`` prepends ``<home>/bin`` for bundled ``gh``.
_STANDARD_TOOL_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def _daytona_path(sandbox_home: str) -> str:
    """Ensure ``~/bin`` (for bundled ``gh``) is first on ``PATH``."""
    return f"{sandbox_home}/bin:{_STANDARD_TOOL_PATH}"


def _posix_sh_gh_install_script(*, bin_dir: str, version: str) -> str:
    """Download official ``gh`` tarball into ``bin_dir`` (POSIX ``sh`` only; no ``pipefail``)."""
    qdir = shlex.quote(bin_dir)
    return f"""
set -eu
BIN={qdir}
mkdir -p "$BIN"
arch=$(uname -m)
case "$arch" in
  x86_64) arch=amd64 ;;
  aarch64|arm64) arch=arm64 ;;
  *) echo "unsupported arch: $arch" >&2; exit 1 ;;
esac
rm -f /tmp/gh.tgz
curl -fsSL "https://github.com/cli/cli/releases/download/v{version}/gh_{version}_linux_$arch.tar.gz" -o /tmp/gh.tgz
tar -xzf /tmp/gh.tgz -C /tmp
cp "/tmp/gh_{version}_linux_$arch/bin/gh" "$BIN/gh"
chmod +x "$BIN/gh"
rm -f /tmp/gh.tgz
"$BIN/gh" version
"""


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
    Put ``gh`` in ``<sandbox_home>/bin`` when it is not already on ``PATH``.

    Uses POSIX ``sh`` (Daytona often runs dash)—no bash-only options like ``pipefail``.
    Disable with ``DAYTONA_INSTALL_GH_CLI=false`` if the image already ships ``gh``.

    ``path_for_check`` is typically :func:`_daytona_path` for ``sandbox_home`` (see
    :func:`create_daytona_agent_session`).
    """
    if not _install_gh_cli_enabled():
        return

    bin_dir = f"{sandbox_home}/bin"
    probe = _exec_sh(
        sandbox,
        "command -v gh >/dev/null 2>&1",
        timeout=60,
        env={"PATH": path_for_check},
    )
    if probe.exit_code == 0:
        return

    version = GITHUB_CLI_VERSION.strip() or "2.88.1"
    script = _posix_sh_gh_install_script(bin_dir=bin_dir, version=version)
    try:
        r = _exec_sh(sandbox, script, timeout=180, env={"PATH": _STANDARD_TOOL_PATH})
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

    Lifecycle caps (see :data:`~constants.DAYTONA_CODER_MAX_MINUTES`): idle auto-stop and
    per-command timeouts align with the coder wall-clock limit; a timer in the coder also
    calls :func:`stop_sandbox` when the wall-clock cap is reached.

    Uses the TypeScript default snapshot so Node/npm/git tooling matches agent prompts.
    """
    client = Daytona()
    idle_stop_min = DAYTONA_CODER_MAX_MINUTES if DAYTONA_CODER_MAX_MINUTES > 0 else 0
    params = CreateSandboxFromSnapshotParams(
        language="typescript",
        env_vars=env_vars,
        labels={"run_id": run_id, "app": "greagent-github-deep-agent"},
        ephemeral=True,
        auto_stop_interval=idle_stop_min,
    )
    sandbox = client.create(params, timeout=create_timeout_sec)
    home = sandbox.get_user_home_dir()
    ensure_github_cli_installed(
        sandbox,
        sandbox_home=home,
        path_for_check=_daytona_path(home),
    )
    cmd_timeout = (
        DAYTONA_CODER_WALL_CLOCK_SEC if DAYTONA_CODER_WALL_CLOCK_SEC > 0 else 30 * 60
    )
    backend = DaytonaSandbox(sandbox=sandbox, timeout=cmd_timeout)
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
