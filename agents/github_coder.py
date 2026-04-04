"""
Deep-agent GitHub coder: clones repos, implements issues, opens PRs.

Invoked via `run_agent_on_issue` (issues) or `run_coder_on_pr` (PRs labeled ``greagent:code``).
Uses a stable workflow ``run_id`` (repo + issue number) for usage rows, stream config,
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
from agents.usage_callback import AgentLlmUsageCallbackHandler
from constants import (
    AGENT_LLM_PROVIDER,
    git_identity_from_env,
)
from logger import get_logger
from model.enums import GitHubWorkflowKind
from services.github.agent_daytona import (
    build_sandbox_env_vars,
    create_daytona_agent_session,
    stop_sandbox,
)
from services.github.pr_conversation_context import (
    fetch_pr_conversation_context_for_llm,
)
from services.github.pr_payload import PROpenedForReview
from services.github.workflow_run_id import (
    github_issue_workflow_run_id,
    github_pr_workflow_run_id,
)
from services.github.workflow_usage import (
    record_github_workflow_usage,
    record_issue_workflow_usage,
)
from services.github.installation_token import (
    get_installation_token_for_repo,
    github_bot_git_identity,
)
from services.github.issue_payload import IssueOpenedForCoder

logger = get_logger(__name__)

_BASE_INSTRUCTIONS = """You are an expert software engineer who implements changes across common stacks.

## Sandbox layout (important)

- ``HOME`` is ``/root``. Clone every GitHub repo to an **absolute** path: ``/root/repos/<repository-name>``.
- Environment variable ``WORKFLOW_REPO_ABS`` is set to that clone root for this run (same value you should use in tools).

## Shell (``execute``)

- Example: ``git clone <url> /root/repos/my-repo`` then ``cd /root/repos/my-repo``.
- Prefer **absolute** paths in shell commands so they do not depend on the current working directory.
- For ``git fetch`` / ``git pull`` / ``git push``, pass a bounded ``timeout`` on ``execute`` (e.g. 300–600 seconds) so a stuck network call does not burn the whole sandbox lifetime.
- Before fetching: run ``git remote -v``. If ``origin`` is plain ``https://github.com/...`` without credentials, set it to use the token: ``git remote set-url origin "https://x-access-token:${GH_TOKEN}@github.com/<owner>/<repo>.git"``. Otherwise ``git fetch`` can hang waiting for a password that never comes.

## Filesystem tools (``read_file``, ``write_file``, ``edit_file``, ``ls``, ``glob``, ``grep``)

Deep Agents **require paths that start with ``/``**. If you pass a relative path like ``repos/foo/bar``, the runtime normalizes it to ``/repos/foo/bar`` at the **filesystem root**, which is **wrong** here: your clone lives under ``/root/repos/``, not ``/repos/``.

- **Always** use the full path: ``/root/repos/<repository-name>/<path-inside-repo>``.
- Good: ``read_file`` on ``/root/repos/localcode-test/src/app.ts``
- Bad: ``repos/localcode-test/src/app.ts``, ``/repos/localcode-test/src/app.ts``, ``/Users/...``, Windows paths.

Before reading files, clone if needed, then ``ls`` on ``/root/repos/<repository-name>`` to confirm paths.

Always start from an empty sandbox: clone first, then explore.

Remember to add a robo emoji 🤖 at the start of every commit message.

Check if the repo exists before cloning; clone into ``/root/repos/<repository-name>`` only.

Commits must use the GitHub App bot identity (GIT_AUTHOR_* / GIT_COMMITTER_* are set in the environment). Do **not** run ``git config user.email`` to a personal address — that would attribute commits to a human instead of the app.

For pull requests and GitHub comments, prefer the ``gh`` CLI (``gh pr create``, ``gh issue comment``, …) with ``GH_TOKEN`` in the environment; it is more reliable than raw ``curl``.
"""


def create_github_coder_agent(
    backend: object,
    *,
    system_prompt: str,
) -> object:
    """
    Build the deep agent graph for the given backend (local virtual FS or Daytona sandbox).

    For ``LocalShellBackend``, construct the backend **inside** ``installation_token_env``
    so ``inherit_env=True`` snapshots ``GH_TOKEN`` and git identity.
    """
    return create_deep_agent(
        model=get_github_deep_agent_llm(),
        system_prompt=system_prompt,
        backend=backend,
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

    ``run_id`` is ``github:{owner}/{repo}#issue-{n}`` (see :mod:`services.github.workflow_run_id`).
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

    full_name = issue.full_name
    clone_url = f"https://x-access-token:$GH_TOKEN@github.com/{full_name}.git"
    system_prompt = _BASE_INSTRUCTIONS
    prompt = f"""In the repository {issue.repo_url}.

Clone root for this repo (use for ``read_file`` / ``ls`` / ``glob``): ``/root/repos/{issue.repo_name}`` — matches ``$WORKFLOW_REPO_ABS``.

**Issue #{issue.issue_number}: {issue.issue_title}**

{issue.issue_body or "(No description provided)"}

Please implement the requested changes:
1. Clone the repo to ``/root/repos/{issue.repo_name}`` if missing: ``git clone {clone_url} /root/repos/{issue.repo_name}`` then ``cd /root/repos/{issue.repo_name}``
2. Run ``git remote set-url origin {clone_url}`` immediately after clone (before ``git fetch``/``git pull``/``git push``) so Git never hangs waiting for credentials.
3. Create a new branch named exactly: agent/issue-{issue.issue_number}
4. Make the required code changes
5. Commit your changes (remember 🤖 in commit message)
6. Push the branch (use ``execute`` with a timeout, e.g. 300s): ``git push origin agent/issue-{issue.issue_number}``
7. Raise a PR against the default branch with a relevant title and body (``gh pr create``). Mention in the body that this PR "Closes #{issue.issue_number}" so that the issue gets auto-closed when the PR is merged.
8. Comment on the pull request with a short summary and a link to the issue.
9. Comment on the issue that the PR was opened and include the PR link.

"""
    run_id = github_issue_workflow_run_id(issue.full_name, issue.issue_number)
    usage_cb = AgentLlmUsageCallbackHandler()
    llm = get_github_deep_agent_llm()
    llm.callbacks = [usage_cb]
    stream_config: dict = {
        "configurable": {"thread_id": run_id},
        "callbacks": [usage_cb],
    }

    daytona_session = None
    try:
        logger.info(
            "GitHub coder using Daytona sandbox (run_id=%s)",
            run_id,
        )
        env_vars = build_sandbox_env_vars(
            token_value,
            git_author=git_author_pair,
            git_committer=git_committer_pair,
            repo_name=issue.repo_name,
        )
        backend, session = create_daytona_agent_session(run_id, env_vars)
        daytona_session = session
        agent = create_github_coder_agent(backend, system_prompt=system_prompt)
        stream_deep_agent(agent, prompt, stream_config)
    finally:
        llm.callbacks = None
        stop_sandbox(daytona_session)
        record_issue_workflow_usage(
            issue,
            run_id,
            usage_cb,
            provider=AGENT_LLM_PROVIDER,
        )


_PR_CODER_SYSTEM_SUFFIX = """

## Pull request task (``greagent:code``)

You are the **coder**, not a reviewer. This run updates an **existing open PR** by committing
real code changes on that PR’s **head branch** and pushing them so the PR diff updates.

- **Do not** treat this as a code review: do not spend the run only on ``gh pr review`` or
  line-by-line commentary. 
- **Do** implement fixes and features: edit files, run tests/lint if appropriate, **commit**
  (🤖 in the message), and **push** to the same head branch that the PR already uses.
- **Do not** open a second PR for this work; push to the existing branch so the current PR
  advances.
- When **Prior discussion** is present, use it as the main spec for what to change (review
  comments, author replies, checklist items).
"""


def run_coder_on_pr(
    pr: PROpenedForReview,
    *,
    access_token: str | None = None,
) -> None:
    """
    Run the code agent on a PR after the ``greagent:code`` label (webhook prepare step
    already moved the PR to ``greagent:in-progress``).

    Uses ``github:{owner}/{repo}#pr-{n}`` as ``run_id`` and records usage as
    :class:`~model.enums.GitHubWorkflowKind` ``code``.
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
    system_prompt = _BASE_INSTRUCTIONS + _PR_CODER_SYSTEM_SUFFIX

    prior_discussion = fetch_pr_conversation_context_for_llm(
        pr.owner,
        pr.repo_name,
        pr.pr_number,
        token_value,
        max_chars=24_000,
    )
    prior_block = ""
    if prior_discussion.strip():
        prior_block = f"""
## Prior discussion on this pull request (from GitHub)

{prior_discussion}

"""

    prompt = f"""In the repository {pr.repo_url}.

Clone root for this repo (use for ``read_file`` / ``ls`` / ``glob``): ``/root/repos/{pr.repo_name}`` — matches ``$WORKFLOW_REPO_ABS``.

**Pull Request #{pr.pr_number}: {pr.pr_title}**

{pr.pr_body or "(No description provided)"}

Base branch: {pr.base_branch}
Head branch: {pr.head_branch}
Head SHA: {pr.head_sha}
{prior_block}
Implement what this PR and the discussion above require—**by changing code on the PR branch**, not by re-reviewing:

1. Clone the repo to ``/root/repos/{pr.repo_name}`` if missing: ``git clone {clone_url} /root/repos/{pr.repo_name}`` then ``cd /root/repos/{pr.repo_name}``
2. Run ``git remote set-url origin {clone_url}`` **before** ``git fetch`` so fetches never hang on credential prompts.
3. Fetch and check out the **PR head branch** (use ``execute`` with a timeout, e.g. 300s): ``git fetch origin`` then ``git checkout {pr.head_branch}`` (create a local tracking branch if needed).
4. Use ``git diff {pr.base_branch}...HEAD`` (or ``origin/{pr.base_branch}`` if needed) to see what the PR currently changes; then **edit the codebase** to satisfy the PR description, title, and any concrete asks in **Prior discussion** (e.g. fix bugs, apply refactors, address review feedback).
5. Commit your work with a 🤖-prefixed message. Do **not** change git author to a personal email.
6. Ensure ``origin`` is still ``{clone_url}``, then push **your branch** so the existing PR updates: ``git push origin {pr.head_branch}`` (bounded ``execute`` timeout).
7. Optionally leave a brief ``gh pr comment {pr.pr_number}`` summarizing what you committed (no need to submit a formal PR review unless the user only wanted commentary).

If there is truly nothing to implement, say so in one PR comment and stop—but default assumption is **ship commits** on ``{pr.head_branch}``.
"""
    run_id = github_pr_workflow_run_id(pr.full_name, pr.pr_number)
    usage_cb = AgentLlmUsageCallbackHandler()
    llm = get_github_deep_agent_llm()
    llm.callbacks = [usage_cb]
    stream_config: dict = {
        "configurable": {"thread_id": run_id},
        "callbacks": [usage_cb],
    }

    os.environ["GH_TOKEN"] = token_value

    daytona_session = None
    try:
        logger.info(
            "GitHub PR coder using Daytona sandbox (run_id=%s)",
            run_id,
        )
        env_vars = build_sandbox_env_vars(
            token_value,
            git_author=git_author_pair,
            git_committer=git_committer_pair,
            repo_name=pr.repo_name,
        )
        backend, session = create_daytona_agent_session(run_id, env_vars)
        daytona_session = session
        agent = create_github_coder_agent(backend, system_prompt=system_prompt)
        stream_deep_agent(agent, prompt, stream_config)
    finally:
        llm.callbacks = None
        stop_sandbox(daytona_session)
        record_github_workflow_usage(
            workflow=GitHubWorkflowKind.code,
            owner=pr.owner,
            repo_name=pr.repo_name,
            github_full_name=pr.full_name,
            github_item_number=pr.pr_number,
            run_id=run_id,
            usage_cb=usage_cb,
            provider=AGENT_LLM_PROVIDER,
            github_sender_login=pr.github_sender_login,
        )
