"""
Deep-agent GitHub coder: clones repos, implements issues, opens PRs.

Invoked via `run_agent_on_issue` (e.g. from `services.github.coder_workflow`).
Uses LangGraph checkpointing (PostgreSQL via ``db.client.get_psycopg_conninfo()``) with a
stable ``thread_id`` per issue (see LangGraph persistence / threads docs).

When ``DAYTONA_API_KEY`` is set, execution uses a `Daytona`_ remote sandbox (``langchain-daytona``);
otherwise the local ``LocalShellBackend`` virtual filesystem under ``./workspace``.

.. _Daytona: https://docs.langchain.com/oss/python/deepagents/sandboxes#daytona
"""

from __future__ import annotations

from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend

from agents.checkpoint import get_checkpointer, github_issue_workflow_thread_id
from agents.deep_agent_stream import stream_deep_agent
from agents.github_llm import get_github_deep_agent_llm
from agents.usage_callback import AgentLlmUsageCallbackHandler
from constants import (
    AGENT_LLM_PROVIDER,
    daytona_sandbox_enabled,
    daytona_sandbox_home,
    get_agent_model_name,
    git_identity_from_env,
)
from logger import get_logger
from services.github.agent_daytona import (
    build_sandbox_env_vars,
    create_daytona_agent_session,
    stop_sandbox,
)
from services.github.workflow_usage import record_issue_workflow_usage
from services.github.installation_token import (
    get_installation_token_for_repo,
    github_bot_git_identity,
    installation_token_env,
)
from services.github.issue_payload import IssueOpenedForCoder

logger = get_logger(__name__)

_BASE_INSTRUCTIONS = """You are a NodeJS expert who knows how to code in TypeScript and all the CLI commands around it.

Your job is to deliver whatever the user asks for.

Folder Structure:
/
|-repos
  |-example-repo-1
  |-example-repo-2
You operate inside a workspace where the root contains a directory "repos" and all repositories are inside this.
If "repos" does not exist yet, create it first (e.g. mkdir -p repos).

## Workspace Rules

- The workspace root is your working directory for shell commands.
- All repositories must live inside "repos" directory.
- When cloning a repo named "example", clone to "repos/example".

Correct example:
git clone https://github.com/user/example repos/example
cd repos/example && git pull

Incorrect:
git clone https://github.com/user/example
cd / && git clone ...

Shell commands must use paths relative to the current directory.

Do NOT use absolute paths such as:
/repos/...

Instead use:

repos/<repo>

Correct:
cd repos/example

Incorrect:
cd /repo/example

Remember to add a robo emoji 🤖 in every commit message of yours in the starting.

Check if the repo exists before cloning, if it does not, then you are free to clone.

Commits must use the GitHub App bot identity (GIT_AUTHOR_* / GIT_COMMITTER_* are set in the environment). Do **not** run ``git config user.email`` to a personal address — that would attribute commits to a human instead of the app.

For pull requests and GitHub comments, prefer the ``gh`` CLI (``gh pr create``, ``gh issue comment``, …) with ``GH_TOKEN`` in the environment; it is more reliable than raw ``curl``.
"""


def build_coder_system_prompt(
    *,
    daytona: bool,
    repo_name: str,
    workflow_repo_abs: str | None,
    sandbox_home: str | None = None,
) -> str:
    """Augment base instructions with backend-specific path hints (Daytona vs local VFS)."""
    if not daytona:
        return _BASE_INSTRUCTIONS
    home = sandbox_home or daytona_sandbox_home()
    abs_hint = workflow_repo_abs or ""
    return (
        _BASE_INSTRUCTIONS
        + f"""

## Daytona sandbox (this run)

- After clone, this repository’s files are under **{abs_hint}** (also in ``$WORKFLOW_REPO_ABS``).
- For ``read_file`` / ``write_file`` / ``edit_file``, use that **absolute** path prefix — do not invent roots like ``/repo/`` or top-level ``/repos/`` (those are wrong).
- Shell ``pwd`` is usually your home (e.g. ``{home}``); ``repos/{repo_name}`` is relative to that home.
- If unsure, run ``printenv WORKFLOW_REPO_ABS`` once instead of searching the filesystem.
"""
    )

def create_github_coder_agent(backend: object, *, system_prompt: str) -> object:
    """
    Build the deep agent graph for the given backend (local virtual FS or Daytona sandbox).

    For ``LocalShellBackend``, construct the backend **inside** ``installation_token_env``
    so ``inherit_env=True`` snapshots ``GH_TOKEN`` and git identity.
    """
    return create_deep_agent(
        model=get_github_deep_agent_llm(),
        system_prompt=system_prompt,
        backend=backend,
        checkpointer=get_checkpointer(),
    )


def run_agent_on_issue(
    issue: IssueOpenedForCoder,
    *,
    access_token: str | None = None,
) -> None:
    """
    Run the GitHub coder agent for a triggered issue (queue label already moved to
    ``greagent:in-progress`` by the webhook). Clones the repo, implements, opens a PR,
    and comments; the HTTP layer sets ``greagent:done`` or ``greagent:error`` afterward.

    Checkpoints are keyed by ``thread_id`` = ``github:{owner}/{repo}#issue-{n}`` so the
    same issue run can be resumed or replayed from stored LangGraph state.
    """
    token_value = access_token or get_installation_token_for_repo(
        issue.owner,
        issue.repo_name,
        github_installation_id=issue.github_installation_id,
    )

    env_identity = git_identity_from_env()
    if env_identity:
        (an, ae), (cn, ce) = env_identity
        git_author_pair = (an, ae)
        git_committer_pair = (
            (cn, ce) if (cn != an or ce != ae) else None
        )
    else:
        api_id = github_bot_git_identity()
        git_author_pair = api_id
        git_committer_pair = None
        if not api_id:
            logger.warning(
                "Could not set GIT_AUTHOR_* for bot commits; set GIT_AUTHOR_NAME and "
                "GIT_AUTHOR_EMAIL in .env, or set GITHUB_APP_SLUG / fix JWT GET /app. "
                "Otherwise git may use local user.name/email."
            )

    full_name = issue.full_name
    clone_url = f"https://x-access-token:$GH_TOKEN@github.com/{full_name}.git"
    use_daytona = daytona_sandbox_enabled()
    sandbox_home = daytona_sandbox_home()
    workflow_repo_abs = f"{sandbox_home}/repos/{issue.repo_name}"
    system_prompt = build_coder_system_prompt(
        daytona=use_daytona,
        repo_name=issue.repo_name,
        workflow_repo_abs=workflow_repo_abs if use_daytona else None,
        sandbox_home=sandbox_home,
    )
    prompt = f"""In the repository {issue.repo_url} (repo folder: repos/{issue.repo_name}):

**Issue #{issue.issue_number}: {issue.issue_title}**

{issue.issue_body or "(No description provided)"}

Please implement the requested changes:
1. Clone the repo to repos/{issue.repo_name} if it doesn't exist (use: git clone {clone_url} repos/{issue.repo_name})
2. Create a new branch named exactly: agent/issue-{issue.issue_number}
3. Make the required code changes
4. Commit your changes (remember 🤖 in commit message)
5. Before pushing, ensure the remote uses the app token (GH_TOKEN in the environment): git remote set-url origin {clone_url}
6. Push the branch: git push origin agent/issue-{issue.issue_number}
7. Raise a PR against the default branch with a relevant title and body (``gh pr create``). Mention in the body that this PR "Closes #{issue.issue_number}" so that the issue gets auto-closed when the PR is merged.
8. Comment on the pull request with a short summary and a link to the issue.
9. Comment on the issue that the PR was opened and include the PR link.

"""
    thread_id = github_issue_workflow_thread_id(issue.full_name, issue.issue_number)
    usage_cb = AgentLlmUsageCallbackHandler()
    llm = get_github_deep_agent_llm()
    llm.callbacks = [usage_cb]
    stream_config: dict = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [usage_cb],
    }

    daytona_session = None
    try:
        if use_daytona:
            logger.info(
                "GitHub coder using Daytona sandbox (thread_id=%s)",
                thread_id,
            )
            env_vars = build_sandbox_env_vars(
                token_value,
                git_author=git_author_pair,
                git_committer=git_committer_pair,
                repo_name=issue.repo_name,
                sandbox_home=sandbox_home,
            )
            backend, session = create_daytona_agent_session(
                thread_id, env_vars, sandbox_home=sandbox_home
            )
            daytona_session = session
            agent = create_github_coder_agent(backend, system_prompt=system_prompt)
            stream_deep_agent(agent, prompt, stream_config)
        else:
            logger.info(
                "GitHub coder using local LocalShellBackend under ./workspace "
                "(set DAYTONA_API_KEY to use Daytona)",
            )
            Path("workspace/repos").mkdir(parents=True, exist_ok=True)
            with installation_token_env(
                token_value,
                git_author=git_author_pair,
                git_committer=git_committer_pair,
            ):
                backend = LocalShellBackend(
                    root_dir="./workspace",
                    virtual_mode=True,
                    inherit_env=True,
                )
                agent = create_github_coder_agent(backend, system_prompt=system_prompt)
                stream_deep_agent(agent, prompt, stream_config)
    finally:
        llm.callbacks = None
        stop_sandbox(daytona_session)
        record_issue_workflow_usage(
            issue,
            thread_id,
            usage_cb,
            provider=AGENT_LLM_PROVIDER,
            fallback_model_name=get_agent_model_name(),
        )
