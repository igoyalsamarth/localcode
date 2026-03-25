"""
Run the GitHub review agent in response to PR events (greagent:review label or auto mode).

Uses the GitHub App installation access token for the repo's installation.
"""

from agents.github_reviewer import run_agent_on_pr
from logger import get_logger
from services.github.client import (
    add_pr_labels,
    comment_on_pr,
    ensure_repo_label_exists,
    remove_pr_label,
)
from services.github.coder_labels import ERROR, REVIEW, REVIEWED
from services.github.installation_token import (
    get_api_token_for_repo,
    get_installation_token_for_repo,
)
from services.github.pr_payload import PROpenedForReview

logger = get_logger(__name__)


def ensure_greagent_review_labels_on_repository(
    owner: str,
    repo_name: str,
    *,
    access_token: str | None = None,
) -> None:
    """Create the ``greagent:review``, ``greagent:reviewed``, and ``greagent:error`` labels on the repo if they are missing."""
    tok = access_token if access_token is not None else get_api_token_for_repo(
        owner, repo_name
    )
    for name in (REVIEW, REVIEWED, ERROR):
        ensure_repo_label_exists(owner, repo_name, tok, name)


def _ensure_greagent_review_labels_exist(
    work: PROpenedForReview, access_token: str
) -> None:
    """Create greagent:review* labels on the repo if they are missing."""
    for name in (REVIEW, REVIEWED, ERROR):
        ensure_repo_label_exists(work.owner, work.repo_name, access_token, name)


def _transition_review_to_reviewed(
    work: PROpenedForReview, access_token: str
) -> None:
    """Replace ``greagent:review`` with ``greagent:reviewed``."""
    remove_pr_label(
        work.owner, work.repo_name, work.pr_number, REVIEW, access_token
    )
    add_pr_labels(
        work.owner,
        work.repo_name,
        work.pr_number,
        access_token,
        [REVIEWED],
    )


def _transition_review_to_error(
    work: PROpenedForReview, access_token: str
) -> None:
    """Replace ``greagent:review`` with ``greagent:error``."""
    remove_pr_label(
        work.owner, work.repo_name, work.pr_number, REVIEW, access_token
    )
    add_pr_labels(
        work.owner,
        work.repo_name,
        work.pr_number,
        access_token,
        [ERROR],
    )


def prepare_pr_for_review_work(work: PROpenedForReview) -> None:
    """
    Ensure labels exist before enqueueing the background agent run.

    Call this synchronously in the webhook before enqueueing the background agent run.
    """
    tok = get_installation_token_for_repo(
        work.owner,
        work.repo_name,
        github_installation_id=work.github_installation_id,
    )
    _ensure_greagent_review_labels_exist(work, tok)


def run_review_agent_for_opened_pr(work: PROpenedForReview) -> None:
    """
    Execute the deep-agent reviewer: clone, checkout branch, review, comment, approve.

    On success: ``greagent:reviewed``. On failure: ``greagent:error`` + error comment.
    """
    tok = get_installation_token_for_repo(
        work.owner,
        work.repo_name,
        github_installation_id=work.github_installation_id,
    )
    try:
        run_agent_on_pr(work, access_token=tok)
    except Exception as e:
        logger.exception(
            "Review agent failed for PR #%s in %s: %s",
            work.pr_number,
            work.full_name,
            e,
        )
        try:
            _transition_review_to_error(work, tok)
        except Exception as label_err:
            logger.exception("Failed to set greagent:error label: %s", label_err)
        try:
            comment_on_pr(
                owner=work.owner,
                repo=work.repo_name,
                pr_number=work.pr_number,
                token=tok,
                body=(
                    "⚠️ Sorry, I encountered an error while reviewing this PR:\n\n"
                    f"```\n{e}\n```"
                ),
            )
        except Exception as comment_err:
            logger.exception("Failed to post error comment: %s", comment_err)
        return

    try:
        _transition_review_to_reviewed(work, tok)
    except Exception as label_err:
        logger.exception(
            "Failed to set greagent:reviewed after successful run: %s", label_err
        )
