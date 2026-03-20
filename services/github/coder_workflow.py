"""
Run the GitHub coder agent in response to issue events (greagent:code label or auto mode).

Uses the GitHub App installation access token for the repo’s installation.
"""

from agents.github_coder import run_agent_on_issue
from logger import get_logger
from services.github.client import (
    add_issue_labels,
    add_issue_reaction,
    comment_on_issue,
    ensure_repo_label_exists,
    remove_issue_label,
)
from services.github.coder_labels import CODE, DONE, ERROR, IN_PROGRESS
from services.github.installation_token import get_api_token_for_repo
from services.github.issue_payload import IssueOpenedForCoder

logger = get_logger(__name__)


def ensure_greagent_labels_on_repository(
    owner: str,
    repo_name: str,
    *,
    access_token: str | None = None,
) -> None:
    """Create the four ``greagent:*`` labels on the repo if they are missing."""
    tok = access_token if access_token is not None else get_api_token_for_repo(
        owner, repo_name
    )
    for name in (CODE, IN_PROGRESS, DONE, ERROR):
        ensure_repo_label_exists(owner, repo_name, tok, name)


def _ensure_greagent_labels_exist(
    work: IssueOpenedForCoder, access_token: str
) -> None:
    """Create greagent:* labels on the repo if they are missing."""
    for name in (CODE, IN_PROGRESS, DONE, ERROR):
        ensure_repo_label_exists(work.owner, work.repo_name, access_token, name)


def _transition_queue_to_in_progress(
    work: IssueOpenedForCoder, access_token: str
) -> None:
    """Replace ``greagent:code`` with ``greagent:in-progress``."""
    remove_issue_label(
        work.owner, work.repo_name, work.issue_number, CODE, access_token
    )
    add_issue_labels(
        work.owner,
        work.repo_name,
        work.issue_number,
        access_token,
        [IN_PROGRESS],
    )


def _transition_in_progress_to_done(
    work: IssueOpenedForCoder, access_token: str
) -> None:
    remove_issue_label(
        work.owner, work.repo_name, work.issue_number, IN_PROGRESS, access_token
    )
    add_issue_labels(
        work.owner,
        work.repo_name,
        work.issue_number,
        access_token,
        [DONE],
    )


def _transition_in_progress_to_error(
    work: IssueOpenedForCoder, access_token: str
) -> None:
    remove_issue_label(
        work.owner, work.repo_name, work.issue_number, IN_PROGRESS, access_token
    )
    add_issue_labels(
        work.owner,
        work.repo_name,
        work.issue_number,
        access_token,
        [ERROR],
    )


def prepare_issue_for_coder_work(work: IssueOpenedForCoder) -> None:
    """
    Move to ``greagent:in-progress``, then add the eyes reaction.

    Call this synchronously in the webhook before enqueueing the background agent run.
    """
    tok = get_api_token_for_repo(work.owner, work.repo_name)
    _ensure_greagent_labels_exist(work, tok)
    _transition_queue_to_in_progress(work, tok)
    add_issue_reaction(
        owner=work.owner,
        repo=work.repo_name,
        issue_number=work.issue_number,
        token=tok,
        reaction="eyes",
    )


def run_coder_agent_for_opened_issue(work: IssueOpenedForCoder) -> None:
    """
    Execute the deep-agent coder: clone, branch, implement, PR, comment.

    On success: ``greagent:done``. On failure: ``greagent:error`` + comment.
    """
    tok = get_api_token_for_repo(work.owner, work.repo_name)
    try:
        run_agent_on_issue(work, access_token=tok)
    except Exception as e:
        logger.exception(
            "Coder agent failed for issue #%s in %s: %s",
            work.issue_number,
            work.full_name,
            e,
        )
        try:
            _transition_in_progress_to_error(work, tok)
        except Exception as label_err:
            logger.exception("Failed to set greagent:error label: %s", label_err)
        try:
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
        except Exception as comment_err:
            logger.exception("Failed to post error comment: %s", comment_err)
        return

    try:
        _transition_in_progress_to_done(work, tok)
    except Exception as label_err:
        logger.exception(
            "Failed to set greagent:done after successful run: %s", label_err
        )
