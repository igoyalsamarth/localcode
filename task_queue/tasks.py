"""Dramatiq tasks for processing GitHub issues and PRs."""

import dramatiq

from db.repo_agent_lock import hold_github_repo_agent_lock
from logger import get_logger
from task_queue.broker import broker

logger = get_logger(__name__)

dramatiq.set_broker(broker)

# Single queue for coder + reviewer so jobs are processed in FIFO order per consumer
# (tighter than splitting across ``github_coder`` / ``github_reviewer`` queues).
_GITHUB_AGENT_QUEUE = "github_agent"
_GITHUB_AGENT_ACTOR_OPTIONS = {"max_retries": 3, "time_limit": 3600000}


@dramatiq.actor(queue_name=_GITHUB_AGENT_QUEUE, **_GITHUB_AGENT_ACTOR_OPTIONS)
def process_github_issue(issue_data: dict) -> None:
    """
    Process a GitHub issue with the coder agent.

    Args:
        issue_data: Dictionary containing issue information (owner, repo, issue_number, etc.)
    """
    from agents.github_coder import run_agent_on_issue
    from services.github.client import comment_on_issue
    from services.github.coder_workflow import (
        _transition_in_progress_to_done,
        _transition_in_progress_to_error,
    )
    from services.github.installation_token import get_installation_token_for_repo
    from services.github.issue_payload import IssueOpenedForCoder

    work = IssueOpenedForCoder(**issue_data)
    logger.info(
        "Worker processing issue: %s/%s#%s",
        work.owner,
        work.repo_name,
        work.issue_number,
    )

    with hold_github_repo_agent_lock(work.github_repo_id):
        try:
            tok = get_installation_token_for_repo(
                work.owner,
                work.repo_name,
                github_installation_id=work.github_installation_id,
            )

            run_agent_on_issue(work, access_token=tok)

            logger.info(
                "Successfully processed issue #%s in %s",
                work.issue_number,
                work.full_name,
            )

            try:
                _transition_in_progress_to_done(work, tok)
            except Exception as label_err:
                logger.exception("Failed to set greagent:done label: %s", label_err)

        except Exception as e:
            logger.exception(
                "Worker failed to process issue #%s in %s/%s: %s",
                work.issue_number,
                work.owner,
                work.repo_name,
                e,
            )

            try:
                tok = get_installation_token_for_repo(
                    work.owner,
                    work.repo_name,
                    github_installation_id=work.github_installation_id,
                )
                _transition_in_progress_to_error(work, tok)
                comment_on_issue(
                    owner=work.owner,
                    repo=work.repo_name,
                    issue_number=work.issue_number,
                    token=tok,
                    body=(
                        "⚠️ Sorry, I encountered an error while working on this issue:\n\n"
                        f"```\n{e}\n```"
                    ),
                )
            except Exception as cleanup_err:
                logger.exception("Failed to handle error cleanup: %s", cleanup_err)

            raise


@dramatiq.actor(queue_name=_GITHUB_AGENT_QUEUE, **_GITHUB_AGENT_ACTOR_OPTIONS)
def process_github_pr_review(pr_data: dict) -> None:
    """
    Process a GitHub PR with the review agent.

    Args:
        pr_data: Dictionary containing PR information (owner, repo, pr_number, etc.)
    """
    from services.github.pr_payload import PROpenedForReview
    from services.github.review_workflow import run_review_agent_for_opened_pr

    work = PROpenedForReview(**pr_data)
    logger.info(
        "Worker processing PR review: %s/%s#%s",
        work.owner,
        work.repo_name,
        work.pr_number,
    )

    with hold_github_repo_agent_lock(work.github_repo_id):
        try:
            run_review_agent_for_opened_pr(work)

            logger.info(
                "Successfully processed PR review #%s in %s",
                work.pr_number,
                work.full_name,
            )

        except Exception as e:
            logger.exception(
                "Worker failed to process PR review #%s in %s/%s: %s",
                work.pr_number,
                work.owner,
                work.repo_name,
                e,
            )

            raise
