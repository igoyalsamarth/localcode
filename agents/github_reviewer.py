"""
Deep-agent GitHub reviewer: clones repos, checks out PR branches, reviews code changes.

Invoked via `run_agent_on_pr` (e.g. from `services.github.review_workflow`).
Uses a stable workflow ``run_id`` (repo + PR number) for usage rows, stream config,
and Daytona labels; the usage table's primary key is unique per execution.

When ``DAYTONA_API_KEY`` is set, execution uses a `Daytona`_ remote sandbox (``langchain-daytona``);
otherwise the local ``LocalShellBackend`` virtual filesystem under ``./workspace``.

.. _Daytona: https://docs.langchain.com/oss/python/deepagents/sandboxes#daytona
"""

from __future__ import annotations

import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend

from agents.deep_agent_stream import stream_deep_agent
from agents.github_llm import get_github_deep_agent_llm
from agents.reviewer_tools import add_inline_review_comment
from agents.usage_callback import AgentLlmUsageCallbackHandler
from constants import (
    AGENT_LLM_PROVIDER,
    daytona_sandbox_enabled,
    daytona_sandbox_home,
    git_identity_from_env,
)
from logger import get_logger
from services.github.agent_daytona import (
    build_sandbox_env_vars,
    create_daytona_agent_session,
    stop_sandbox,
)
from services.github.workflow_run_id import github_pr_workflow_run_id
from services.github.workflow_usage import record_pr_workflow_usage
from services.github.installation_token import (
    get_installation_token_for_repo,
    github_bot_git_identity,
    installation_token_env,
)
from services.github.pr_payload import PROpenedForReview

logger = get_logger(__name__)

_BASE_INSTRUCTIONS = """You are a NodeJS expert who knows how to review TypeScript code and all the CLI commands around it.

Your job is to review pull requests and provide constructive feedback.

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

Always start by cloning the repository as you start in an empty sandbox.

For GitHub operations, prefer the ``gh`` CLI (``gh pr review``, ``gh pr comment``, …) with ``GH_TOKEN`` in the environment; it is more reliable than raw ``curl``.
"""


def build_reviewer_system_prompt(
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

- After clone, this repository's files are under **{abs_hint}** (also in ``$WORKFLOW_REPO_ABS``).
- For ``read_file`` / ``write_file`` / ``edit_file``, use that **absolute** path prefix — do not invent roots like ``/repo/`` or top-level ``/repos/`` (those are wrong).
- Shell ``pwd`` is usually your home (e.g. ``{home}``); ``repos/{repo_name}`` is relative to that home.
- If unsure, run ``printenv WORKFLOW_REPO_ABS`` once instead of searching the filesystem.
"""
    )


def create_github_reviewer_agent(backend: object, *, system_prompt: str) -> object:
    """
    Build the deep agent graph for the given backend (local virtual FS or Daytona sandbox).

    For ``LocalShellBackend``, construct the backend **inside** ``installation_token_env``
    so ``inherit_env=True`` snapshots ``GH_TOKEN`` and git identity.
    """
    return create_deep_agent(
        model=get_github_deep_agent_llm(),
        system_prompt=system_prompt,
        backend=backend,
        tools=[add_inline_review_comment],
    )


def run_agent_on_pr(
    pr: PROpenedForReview,
    *,
    access_token: str | None = None,
) -> None:
    """
    Run the GitHub review agent for a triggered PR (``opened`` / ``synchronize`` in auto
    mode, or ``labeled`` with ``greagent:review`` for an explicit run or rerun). The webhook
    prepare step sets ``greagent:reviewing`` before this runs. Clones
    the repo, checks out the branch, reviews changes, comments, and approves if all looks good.

    ``run_id`` is ``github:{owner}/{repo}#pr-{n}`` (see :mod:`services.github.workflow_run_id`).
    """
    token_value = access_token or get_installation_token_for_repo(
        pr.owner,
        pr.repo_name,
        github_installation_id=pr.github_installation_id,
    )

    env_identity = git_identity_from_env()
    if env_identity:
        (an, ae), (cn, ce) = env_identity
        git_author_pair = (an, ae)
        git_committer_pair = (cn, ce) if (cn != an or ce != ae) else None
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

    full_name = pr.full_name
    clone_url = f"https://x-access-token:$GH_TOKEN@github.com/{full_name}.git"
    use_daytona = daytona_sandbox_enabled()
    sandbox_home = daytona_sandbox_home()
    workflow_repo_abs = f"{sandbox_home}/repos/{pr.repo_name}"
    system_prompt = build_reviewer_system_prompt(
        daytona=use_daytona,
        repo_name=pr.repo_name,
        workflow_repo_abs=workflow_repo_abs if use_daytona else None,
        sandbox_home=sandbox_home,
    )
    prompt = f"""In the repository {pr.repo_url} (repo folder: repos/{pr.repo_name}):

**Pull Request #{pr.pr_number}: {pr.pr_title}**

{pr.pr_body or "(No description provided)"}

Base branch: {pr.base_branch}
Head branch: {pr.head_branch}
Head SHA: {pr.head_sha}

Please review this pull request:

1. Clone the repo to repos/{pr.repo_name} if it doesn't exist (use: git clone {clone_url} repos/{pr.repo_name})
2. Checkout the PR branch: git checkout {pr.head_branch} (or git fetch origin {pr.head_branch} && git checkout {pr.head_branch})
3. Compare the changes with the base branch: git diff {pr.base_branch}...{pr.head_branch}

4. Review the code changes for:
   - Code quality and best practices
   - Potential bugs or issues
   - Security concerns
   - Performance implications

5. Add inline review comments on specific lines using the `add_inline_review_comment` tool:
   - For suggestions on specific code blocks, use the tool to comment directly on those lines
   - For multi-line suggestions, specify both start_line and line parameters
   - Use clear, constructive language in your comments
   - Examples:
     * Single line: add_inline_review_comment(path="src/utils.ts", line=42, body="Consider using const instead of let")
     * Multi-line: add_inline_review_comment(path="src/api.ts", line=50, start_line=45, body="This block could be refactored")

6. After adding inline comments, post a summary comment using:
   gh pr comment {pr.pr_number} --body "## Review Summary

   I've reviewed the changes and added inline comments on specific lines.

   **Key Points:**
   - [List main observations]

   **Overall Assessment:**
   [Your verdict]"

7. Finally, submit your review:
   - If everything looks good: gh pr review {pr.pr_number} --approve --body "LGTM! See inline comments for minor suggestions."
   - If changes needed: gh pr review {pr.pr_number} --request-changes --body "Please address the inline comments."
   - If just commenting: gh pr review {pr.pr_number} --comment --body "See inline comments for feedback."

Remember: Use inline comments for specific code feedback, and the summary comment for overall observations.
"""
    run_id = github_pr_workflow_run_id(pr.full_name, pr.pr_number)
    usage_cb = AgentLlmUsageCallbackHandler()
    llm = get_github_deep_agent_llm()
    llm.callbacks = [usage_cb]
    stream_config: dict = {
        "configurable": {"thread_id": run_id},
        "callbacks": [usage_cb],
    }

    # PR context for inline review tool (``agents.reviewer_tools``)
    os.environ["GITHUB_PR_OWNER"] = pr.owner
    os.environ["GITHUB_PR_REPO"] = pr.repo_name
    os.environ["GITHUB_PR_NUMBER"] = str(pr.pr_number)
    os.environ["GITHUB_PR_HEAD_SHA"] = pr.head_sha

    # LangChain tools run in this worker process. Daytona only puts GH_TOKEN in the
    # sandbox env, so without this the inline review tool sees no token on the host.
    _previous_gh_token = os.environ.get("GH_TOKEN")
    os.environ["GH_TOKEN"] = token_value

    daytona_session = None
    try:
        if use_daytona:
            logger.info(
                "GitHub reviewer using Daytona sandbox (run_id=%s)",
                run_id,
            )
            env_vars = build_sandbox_env_vars(
                token_value,
                git_author=git_author_pair,
                git_committer=git_committer_pair,
                repo_name=pr.repo_name,
                sandbox_home=sandbox_home,
            )
            env_vars.update(
                {
                    "GITHUB_PR_OWNER": pr.owner,
                    "GITHUB_PR_REPO": pr.repo_name,
                    "GITHUB_PR_NUMBER": str(pr.pr_number),
                    "GITHUB_PR_HEAD_SHA": pr.head_sha,
                }
            )
            backend, session = create_daytona_agent_session(
                run_id, env_vars, sandbox_home=sandbox_home
            )
            daytona_session = session
            agent = create_github_reviewer_agent(backend, system_prompt=system_prompt)
            stream_deep_agent(agent, prompt, stream_config)
        else:
            logger.info(
                "GitHub reviewer using local LocalShellBackend under ./workspace "
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
                agent = create_github_reviewer_agent(
                    backend, system_prompt=system_prompt
                )
                stream_deep_agent(agent, prompt, stream_config)
    finally:
        if _previous_gh_token is None:
            os.environ.pop("GH_TOKEN", None)
        else:
            os.environ["GH_TOKEN"] = _previous_gh_token
        llm.callbacks = None
        stop_sandbox(daytona_session)
        record_pr_workflow_usage(
            pr,
            run_id,
            usage_cb,
            provider=AGENT_LLM_PROVIDER,
        )
