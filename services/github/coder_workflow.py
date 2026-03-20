"""
Run the GitHub coder agent in response to issue events (greagent:code label).
"""

from agents.github_coder import run_agent_on_issue
from constants import token
from logger import get_logger
from services.github.client import (
    add_issue_labels,
    add_issue_reaction,
    comment_on_issue,
    ensure_repo_label_exists,
    remove_issue_label,
)
from services.github.coder_labels import CODE, DONE, ERROR, IN_PROGRESS
from services.github.issue_payload import IssueOpenedForCoder

logger = get_logger(__name__)


def ensure_greagent_labels_on_repository(owner: str, repo_name: str) -> None:
    """Create the four ``greagent:*`` labels on the repo if they are missing."""
    for name in (CODE, IN_PROGRESS, DONE, ERROR):
        ensure_repo_label_exists(owner, repo_name, token, name)


def _ensure_greagent_labels_exist(work: IssueOpenedForCoder) -> None:
    """Create greagent:* labels on the repo if they are missing."""
    ensure_greagent_labels_on_repository(work.owner, work.repo_name)


def _transition_queue_to_in_progress(work: IssueOpenedForCoder) -> None:
    """Replace ``greagent:code`` with ``greagent:in-progress``."""
    remove_issue_label(
        work.owner, work.repo_name, work.issue_number, CODE, token
    )
    add_issue_labels(
        work.owner,
        work.repo_name,
        work.issue_number,
        token,
        [IN_PROGRESS],
    )


def _transition_in_progress_to_done(work: IssueOpenedForCoder) -> None:
    remove_issue_label(
        work.owner, work.repo_name, work.issue_number, IN_PROGRESS, token
    )
    add_issue_labels(
        work.owner,
        work.repo_name,
        work.issue_number,
        token,
        [DONE],
    )


def _transition_in_progress_to_error(work: IssueOpenedForCoder) -> None:
    remove_issue_label(
        work.owner, work.repo_name, work.issue_number, IN_PROGRESS, token
    )
    add_issue_labels(
        work.owner,
        work.repo_name,
        work.issue_number,
        token,
        [ERROR],
    )


def prepare_issue_for_coder_work(work: IssueOpenedForCoder) -> None:
    """
    Move to ``greagent:in-progress``, then add the eyes reaction.

    Call this synchronously in the webhook before enqueueing the background agent run.
    """
    _ensure_greagent_labels_exist(work)
    _transition_queue_to_in_progress(work)
    add_issue_reaction(
        owner=work.owner,
        repo=work.repo_name,
        issue_number=work.issue_number,
        token=token,
        reaction="eyes",
    )


def run_coder_agent_for_opened_issue(work: IssueOpenedForCoder) -> None:
    """
    Execute the deep-agent coder: clone, branch, implement, PR, comment.

    On success: ``greagent:done``. On failure: ``greagent:error`` + comment.
    """
    try:
        run_agent_on_issue(work)
    except Exception as e:
        logger.exception(
            "Coder agent failed for issue #%s in %s: %s",
            work.issue_number,
            work.full_name,
            e,
        )
        try:
            _transition_in_progress_to_error(work)
        except Exception as label_err:
            logger.exception("Failed to set greagent:error label: %s", label_err)
        try:
            comment_on_issue(
                owner=work.owner,
                repo=work.repo_name,
                issue_number=work.issue_number,
                token=token,
                body=(
                    "⚠️ Sorry, I encountered an error while working on this issue:\n\n"
                    f"```\n{e}\n```"
                ),
            )
        except Exception as comment_err:
            logger.exception("Failed to post error comment: %s", comment_err)
        return

    try:
        _transition_in_progress_to_done(work)
    except Exception as label_err:
        logger.exception(
            "Failed to set greagent:done after successful run: %s", label_err
        )
