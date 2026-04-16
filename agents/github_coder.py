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
import threading
from collections.abc import Callable

from deepagents import create_deep_agent

from agents.deep_agent_stream import stream_deep_agent
from agents.github_llm import get_github_deep_agent_llm
from agents.usage_callback import AgentLlmUsageCallbackHandler
from constants import (
    AGENT_LLM_PROVIDER,
    DAYTONA_CODER_WALL_CLOCK_SEC,
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


def _run_stream_with_daytona_wall_clock(
    session_holder: list,
    stream_work: Callable[[], None],
    *,
    run_label: str,
) -> None:
    """
    Hard wall-clock limit for the coder sandbox: stop Daytona after N seconds so the
    sandbox is torn down even if the deep agent stream is still running.
    """
    max_sec = DAYTONA_CODER_WALL_CLOCK_SEC
    if max_sec <= 0:
        stream_work()
        return

    def _wall_clock_stop() -> None:
        sess = session_holder[0] if session_holder else None
        if sess is None:
            return
        logger.warning(
            "%s: Daytona coder sandbox wall-clock limit (%ss) reached; stopping sandbox",
            run_label,
            max_sec,
        )
        stop_sandbox(sess)

    timer = threading.Timer(float(max_sec), _wall_clock_stop)
    timer.daemon = True
    timer.start()
    try:
        stream_work()
    finally:
        timer.cancel()


_BASE_INSTRUCTIONS = """You are an expert software engineer who implements changes across common stacks.

Your job is to review pull requests and provide constructive feedback.

Folder Structure:
/
|-repos
  |-example-repo-1
  |-example-repo-2
You operate inside a sandbox where you are only allowed to perform actions in children directories (repos/<repo-name>).

## Workspace Rules

- The workspace `repos/<repo-name>` is your working directory for shell commands.
- All repositories must live inside "repos" directory.
- When cloning a repo named "example", clone to "repos/example".

Correct example:
git clone https://github.com/<repo-name>/example repos/<repo-name>
cd repos/<repo-name> && git pull

Incorrect:
git clone https://github.com/<repo-name>/example
cd / && git clone ...

Shell commands must use paths relative to the current directory.

Do NOT use absolute paths such as:
/repos/...

Instead use:
repos/<repo-name>

Correct:
cd repos/<repo-name>

Incorrect:
cd /repo/<repo-name>

pwd will be `/home/daytona/`, consider this when doing file-ops.
For Example:
read_file /home/daytona/repos/<repos-name>

Always start by cloning the repository as you start in an empty sandbox.

Remember to add a robo emoji 🤖 in every commit message of yours in the starting.

Check if the repo exists before cloning, if it does not, then you are free to clone.

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
    prompt = f"""In the repository {issue.repo_url} (repo folder: repos/{issue.repo_name}):

For read_file, write_file, and similar tools, paths are always under that folder, e.g. ``repos/{issue.repo_name}/src/app.ts`` — never ``/Users/...`` or absolute host paths.

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
    run_id = github_issue_workflow_run_id(issue.full_name, issue.issue_number)
    usage_cb = AgentLlmUsageCallbackHandler()
    llm = get_github_deep_agent_llm()
    llm.callbacks = [usage_cb]
    stream_config: dict = {
        "configurable": {"thread_id": run_id},
        "callbacks": [usage_cb],
    }

    daytona_session = None
    session_holder: list = [None]
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
        session_holder[0] = session
        agent = create_github_coder_agent(backend, system_prompt=system_prompt)

        def _stream_issue() -> None:
            stream_deep_agent(agent, prompt, stream_config)

        _run_stream_with_daytona_wall_clock(
            session_holder,
            _stream_issue,
            run_label=f"github:{full_name}#issue-{issue.issue_number}",
        )
    finally:
        session_holder[0] = None
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

    prompt = f"""In the repository {pr.repo_url} (repo folder: repos/{pr.repo_name}):

For read_file, write_file, and similar tools, paths are always under that folder, e.g. ``repos/{pr.repo_name}/src/app.ts`` — never ``/Users/...`` or absolute host paths.

**Pull Request #{pr.pr_number}: {pr.pr_title}**

{pr.pr_body or "(No description provided)"}

Base branch: {pr.base_branch}
Head branch: {pr.head_branch}
Head SHA: {pr.head_sha}
{prior_block}
Implement what this PR and the discussion above require—**by changing code on the PR branch**, not by re-reviewing:

1. Clone the repo to repos/{pr.repo_name} if it doesn't exist (use: git clone {clone_url} repos/{pr.repo_name})
2. Fetch the latest and check out the **PR head branch** (the branch that already backs this PR), e.g.:
   ``git fetch origin`` then ``git checkout {pr.head_branch}`` (create a local tracking branch if needed).
3. Use ``git diff {pr.base_branch}...HEAD`` (or ``origin/{pr.base_branch}`` if needed) to see what the PR currently changes; then **edit the codebase** to satisfy the PR description, title, and any concrete asks in **Prior discussion** (e.g. fix bugs, apply refactors, address review feedback).
4. Commit your work with a 🤖-prefixed message. Do **not** change git author to a personal email.
5. Point ``origin`` at the token remote and push **your branch** so the existing PR updates:
   ``git remote set-url origin {clone_url}`` then ``git push origin {pr.head_branch}``
6. Optionally leave a brief ``gh pr comment {pr.pr_number}`` summarizing what you committed (no need to submit a formal PR review unless the user only wanted commentary).

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
    session_holder: list = [None]
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
        session_holder[0] = session
        agent = create_github_coder_agent(backend, system_prompt=system_prompt)

        def _stream_pr() -> None:
            stream_deep_agent(agent, prompt, stream_config)

        _run_stream_with_daytona_wall_clock(
            session_holder,
            _stream_pr,
            run_label=f"github:{full_name}#pr-{pr.pr_number}",
        )
    finally:
        session_holder[0] = None
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
            github_repo_id=pr.github_repo_id,
            github_installation_id=pr.github_installation_id,
        )
