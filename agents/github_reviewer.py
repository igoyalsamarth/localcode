"""
Deep-agent GitHub reviewer: clones repos, checks out PR branches, reviews code changes.

Invoked via `run_agent_on_pr` (e.g. from `services.github.review_workflow`).
Uses LangGraph checkpointing (PostgreSQL via ``db.client.get_psycopg_conninfo()``) with a
stable ``thread_id`` per PR (see LangGraph persistence / threads docs).

When ``DAYTONA_API_KEY`` is set, execution uses a `Daytona`_ remote sandbox (``langchain-daytona``);
otherwise the local ``LocalShellBackend`` virtual filesystem under ``./workspace``.

.. _Daytona: https://docs.langchain.com/oss/python/deepagents/sandboxes#daytona
"""

from __future__ import annotations

import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_ollama import ChatOllama

from agents.checkpoint import get_checkpointer
from agents.reviewer_tools import add_inline_review_comment
from agents.usage_callback import CoderLlmUsageCallbackHandler
from constants import (
    CODER_LLM_PROVIDER,
    OLLAMA_BASE_URL,
    daytona_coder_enabled,
    daytona_coder_home,
    get_coder_model_name,
    git_identity_from_env,
)
from logger import get_logger
from services.github.review_usage import record_review_workflow_usage
from services.github.coder_daytona import (
    build_sandbox_env_vars,
    create_daytona_coder_session,
    stop_sandbox,
)
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
    coder_repo_abs: str | None,
    coder_home: str | None = None,
) -> str:
    """Augment base instructions with backend-specific path hints (Daytona vs local VFS)."""
    if not daytona:
        return _BASE_INSTRUCTIONS
    home = coder_home or daytona_coder_home()
    abs_hint = coder_repo_abs or ""
    return (
        _BASE_INSTRUCTIONS
        + f"""

## Daytona sandbox (this run)

- After clone, this repository's files are under **{abs_hint}** (also in ``$CODER_REPO_ABS``).
- For ``read_file`` / ``write_file`` / ``edit_file``, use that **absolute** path prefix — do not invent roots like ``/repo/`` or top-level ``/repos/`` (those are wrong).
- Shell ``pwd`` is usually your home (e.g. ``{home}``); ``repos/{repo_name}`` is relative to that home.
- If unsure, run ``printenv CODER_REPO_ABS`` once instead of searching the filesystem.
"""
    )


llm = ChatOllama(
    model=get_coder_model_name(),
    base_url=OLLAMA_BASE_URL,
    max_retries=10,
    timeout=120,
)


def create_github_reviewer_agent(backend: object, *, system_prompt: str) -> object:
    """
    Build the deep agent graph for the given backend (local virtual FS or Daytona sandbox).

    For ``LocalShellBackend``, construct the backend **inside** ``installation_token_env``
    so ``inherit_env=True`` snapshots ``GH_TOKEN`` and git identity.
    """
    return create_deep_agent(
        model=llm,
        system_prompt=system_prompt,
        backend=backend,
        checkpointer=get_checkpointer(),
        tools=[add_inline_review_comment],
    )


def _stream_agent(agent: object, user_prompt: str, config: dict) -> None:
    for chunk in agent.stream(
        {
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ]
        },
        config,
        stream_mode="messages",
        subgraphs=True,
        version="v2",
    ):
        if chunk["type"] == "messages":
            msg, _metadata = chunk["data"]

            is_subagent = any(s.startswith("tools:") for s in chunk["ns"])
            source = (
                next((s for s in chunk["ns"] if s.startswith("tools:")), "main")
                if is_subagent
                else "main"
            )

            tool_call_chunks = getattr(msg, "tool_call_chunks", None) or []
            if tool_call_chunks:
                for tc in tool_call_chunks:
                    if tc.get("name"):
                        print(f"[{source}] Tool call: {tc['name']}")
                    if tc.get("args"):
                        print(tc["args"], end="", flush=True)

            if msg.type == "tool":
                print(f"[{source}] Tool result [{msg.name}]: {str(msg.content)[:150]}")

            if msg.type == "ai" and msg.content and not tool_call_chunks:
                print(msg.content, end="", flush=True)

        print()


def reviewer_thread_id(full_name: str, pr_number: int) -> str:
    """
    Stable ``thread_id`` for ``config["configurable"]["thread_id"]``.

    The checkpointer keys state by ``thread_id``; reuse the same id to resume or
    inspect state via ``graph.get_state`` / ``get_state_history`` (see persistence docs).
    """
    return f"github:{full_name}#pr-{pr_number}"


def run_agent_on_pr(
    pr: PROpenedForReview,
    *,
    access_token: str | None = None,
) -> None:
    """
    Run the GitHub review agent for a triggered PR (label already moved to
    ``greagent:review`` by the webhook if tag mode). Clones the repo, checks out the branch,
    reviews changes, comments, and approves if all looks good.

    Checkpoints are keyed by ``thread_id`` = ``github:{owner}/{repo}#pr-{n}`` so the
    same PR run can be resumed or replayed from stored LangGraph state.
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
    use_daytona = daytona_coder_enabled()
    coder_home = daytona_coder_home()
    coder_repo_abs = f"{coder_home}/repos/{pr.repo_name}"
    system_prompt = build_reviewer_system_prompt(
        daytona=use_daytona,
        repo_name=pr.repo_name,
        coder_repo_abs=coder_repo_abs if use_daytona else None,
        coder_home=coder_home,
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
    thread_id = reviewer_thread_id(pr.full_name, pr.pr_number)
    usage_cb = CoderLlmUsageCallbackHandler()
    llm.callbacks = [usage_cb]
    stream_config: dict = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [usage_cb],
    }

    # Set environment variables for the review tools
    os.environ["REVIEW_OWNER"] = pr.owner
    os.environ["REVIEW_REPO"] = pr.repo_name
    os.environ["REVIEW_PR_NUMBER"] = str(pr.pr_number)
    os.environ["REVIEW_HEAD_SHA"] = pr.head_sha

    daytona_session = None
    try:
        if use_daytona:
            logger.info(
                "GitHub reviewer using Daytona sandbox (thread_id=%s)",
                thread_id,
            )
            env_vars = build_sandbox_env_vars(
                token_value,
                git_author=git_author_pair,
                git_committer=git_committer_pair,
                repo_name=pr.repo_name,
                coder_home=coder_home,
            )
            # Add review context to Daytona env vars
            env_vars.update(
                {
                    "REVIEW_OWNER": pr.owner,
                    "REVIEW_REPO": pr.repo_name,
                    "REVIEW_PR_NUMBER": str(pr.pr_number),
                    "REVIEW_HEAD_SHA": pr.head_sha,
                }
            )
            backend, session = create_daytona_coder_session(
                thread_id, env_vars, coder_home=coder_home
            )
            daytona_session = session
            agent = create_github_reviewer_agent(backend, system_prompt=system_prompt)
            _stream_agent(agent, prompt, stream_config)
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
                _stream_agent(agent, prompt, stream_config)
    finally:
        llm.callbacks = None
        stop_sandbox(daytona_session)
        record_review_workflow_usage(
            pr,
            thread_id,
            usage_cb,
            provider=CODER_LLM_PROVIDER,
            fallback_model_name=get_coder_model_name(),
        )
