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

from deepagents import create_deep_agent

from agents.deep_agent_stream import stream_deep_agent
from agents.github_llm import get_github_deep_agent_llm
from agents.reviewer_tools import add_inline_review_comment
from agents.usage_callback import AgentLlmUsageCallbackHandler
from constants import (
    AGENT_LLM_PROVIDER,
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
)
from services.github.pr_payload import PROpenedForReview

logger = get_logger(__name__)

_BASE_INSTRUCTIONS = """You are an expert reviewer for polyglot codebases.

Your job is to review pull requests and provide constructive feedback.

## Sandbox layout (important)

- ``HOME`` is ``/root``. Clone every GitHub repo to an **absolute** path: ``/root/repos/<repository-name>``.
- Environment variable ``WORKFLOW_REPO_ABS`` is set to that clone root for this run (same value you should use in tools).

## Shell (``execute``)

- Example: ``git clone <url> /root/repos/my-repo`` then ``cd /root/repos/my-repo``.
- Prefer **absolute** paths in shell commands so they do not depend on the current working directory.
- For ``git fetch`` / ``git pull`` / ``git push``, pass a bounded ``timeout`` on ``execute`` (e.g. 300–600 seconds) so a stuck network call does not burn the whole sandbox lifetime.
- Before fetching: run ``git remote -v``. If ``origin`` is plain ``https://github.com/...`` without credentials, set it to use the token: ``git remote set-url origin "https://x-access-token:${GH_TOKEN}@github.com/<owner>/<repo>.git"`` (same pattern as clone). Otherwise ``git fetch`` can hang waiting for a password that never comes.

## Filesystem tools (``read_file``, ``write_file``, ``edit_file``, ``ls``, ``glob``, ``grep``)

Deep Agents **require paths that start with ``/``**. If you pass a relative path like ``repos/foo/bar``, the runtime normalizes it to ``/repos/foo/bar`` at the **filesystem root**, which is **wrong** here: your clone lives under ``/root/repos/``, not ``/repos/``.

- **Always** use the full path: ``/root/repos/<repository-name>/<path-inside-repo>``.
- Good: ``read_file`` on ``/root/repos/localcode-test/src/app.ts``
- Bad: ``repos/localcode-test/src/app.ts``, ``/repos/localcode-test/src/app.ts``, ``/root/repos/...`` before you cloned, ``/Users/...``, Windows paths.

Before reading files, clone if needed, then ``ls`` on ``/root/repos/<repository-name>`` to confirm paths.

Always start from an empty sandbox: clone first, then explore.

For GitHub operations, prefer the ``gh`` CLI (``gh pr review``, ``gh pr comment``, …) with ``GH_TOKEN`` in the environment; it is more reliable than raw ``curl``.
"""


def create_github_reviewer_agent(backend: object, *, system_prompt: str) -> object:
    """
    Build the deep agent graph for the given backend (Daytona sandbox).

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
    system_prompt = _BASE_INSTRUCTIONS
    prompt = f"""In the repository {pr.repo_url}.

Clone root for this repo (use for ``read_file`` / ``ls`` / ``glob``): ``/root/repos/{pr.repo_name}`` — matches ``$WORKFLOW_REPO_ABS`` in the environment.

**Pull Request #{pr.pr_number}: {pr.pr_title}**

{pr.pr_body or "(No description provided)"}

Base branch: {pr.base_branch}
Head branch: {pr.head_branch}
Head SHA: {pr.head_sha}

Please review this pull request:

1. Clone the repo to ``/root/repos/{pr.repo_name}`` if missing: ``git clone {clone_url} /root/repos/{pr.repo_name}``
2. ``cd /root/repos/{pr.repo_name}``. Before any ``git fetch``/``git pull``, run ``git remote set-url origin {clone_url}`` so the remote always carries the app token (avoids hangs on credential prompts).
3. Check out the PR branch (use ``execute`` with a timeout, e.g. 300s): ``git fetch origin {pr.head_branch} && git checkout {pr.head_branch}`` (or equivalent).
4. Compare the changes with the base branch: ``git diff {pr.base_branch}...{pr.head_branch}``

5. Review the code changes for:
   - Code quality and best practices
   - Potential bugs or issues
   - Security concerns
   - Performance implications

6. Add inline review comments on specific lines using the `add_inline_review_comment` tool:
   - For suggestions on specific code blocks, use the tool to comment directly on those lines, with suggestions inside ```suggestions ... ``` block, this will give the user an option to commit the suggestion directly.
   - For multi-line suggestions, specify both start_line and line parameters
   - Use clear, constructive language in your comments
   - Examples:
     * Single line: add_inline_review_comment(path="src/utils.ts", line=42, body="Consider using const instead of let")
     * Multi-line: add_inline_review_comment(path="src/api.ts", line=50, start_line=45, body="This block could be refactored")

7. After adding inline comments, post a summary comment using:
   gh pr comment {pr.pr_number} --body "## Review Summary

   I've reviewed the changes and added inline comments on specific lines.

   **Key Points:**
   - [List main observations]

   **Overall Assessment:**
   [Your verdict]"

8. Finally, submit your review:
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
    os.environ["GH_TOKEN"] = token_value

    daytona_session = None
    try:
        logger.info(
            "GitHub reviewer using Daytona sandbox (run_id=%s)",
            run_id,
        )
        env_vars = build_sandbox_env_vars(
            token_value,
            git_author=git_author_pair,
            git_committer=git_committer_pair,
            repo_name=pr.repo_name,
        )
        env_vars.update(
            {
                "GITHUB_PR_OWNER": pr.owner,
                "GITHUB_PR_REPO": pr.repo_name,
                "GITHUB_PR_NUMBER": str(pr.pr_number),
                "GITHUB_PR_HEAD_SHA": pr.head_sha,
            }
        )
        backend, session = create_daytona_agent_session(run_id, env_vars)
        daytona_session = session
        agent = create_github_reviewer_agent(backend, system_prompt=system_prompt)
        stream_deep_agent(agent, prompt, stream_config)

    finally:
        llm.callbacks = None
        stop_sandbox(daytona_session)
        record_pr_workflow_usage(
            pr,
            run_id,
            usage_cb,
            provider=AGENT_LLM_PROVIDER,
        )
