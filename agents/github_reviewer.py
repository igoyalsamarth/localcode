"""Local GitHub reviewer pipeline backed by repository cloning and tree-sitter."""

from __future__ import annotations

from agents.github_llm import get_github_deep_agent_llm
from agents.usage_callback import AgentLlmUsageCallbackHandler
from constants import AGENT_LLM_PROVIDER
from logger import get_logger
from services.github.reviewer_local import (
    build_repository_snapshot,
    clone_or_prepare_repo,
    collect_relevant_context,
    fetch_previous_comments,
    fetch_pr_file_diffs,
    generate_review_decision,
    publish_review,
    remove_reviewer_clone,
)
from services.github.workflow_run_id import github_pr_workflow_run_id
from services.github.workflow_usage import record_pr_workflow_usage
from services.github.installation_token import get_installation_token_for_repo
from services.github.pr_payload import PROpenedForReview

logger = get_logger(__name__)


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
    run_id = github_pr_workflow_run_id(pr.full_name, pr.pr_number)
    usage_cb = AgentLlmUsageCallbackHandler()
    llm = get_github_deep_agent_llm()
    previous_callbacks = llm.callbacks
    llm.callbacks = [usage_cb]
    try:
        logger.info(
            "GitHub reviewer using local tree-sitter pipeline (run_id=%s)", run_id
        )
        repo_dir = clone_or_prepare_repo(pr, token_value)
        snapshot = build_repository_snapshot(repo_dir)
        print(snapshot)
        file_diffs = fetch_pr_file_diffs(
            pr.owner, pr.repo_name, pr.pr_number, token_value
        )
        print(file_diffs)
        relevant_context = collect_relevant_context(snapshot, file_diffs)
        print(relevant_context)
        previous_comments = fetch_previous_comments(
            pr.owner,
            pr.repo_name,
            pr.pr_number,
            token_value,
        )
        print(previous_comments)
        decision = generate_review_decision(
            pr,
            file_diffs,
            relevant_context,
            previous_comments,
        )
        print(decision)
        publish_review(pr, token_value, decision, file_diffs)
    finally:
        remove_reviewer_clone(pr)
        llm.callbacks = previous_callbacks
        record_pr_workflow_usage(
            pr,
            run_id,
            usage_cb,
            provider=AGENT_LLM_PROVIDER,
        )
