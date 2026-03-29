"""Notify on GitHub when a run is skipped due to low wallet balance."""

from __future__ import annotations

from constants import CLIENT_URL
from services.github.client import comment_on_issue, comment_on_pr
from services.github.installation_token import get_installation_token_for_repo
from services.github.issue_payload import IssueOpenedForCoder
from services.github.pr_payload import PROpenedForReview


def _insufficient_wallet_comment_body() -> str:
    base = CLIENT_URL.rstrip("/")
    return (
        "Greagent cannot start this run because your organization wallet balance is below "
        "**$2.00 USD**. Please add funds in [billing settings]("
        f"{base}/settings/billing), then try again."
    )


def notify_insufficient_wallet_for_issue(work: IssueOpenedForCoder) -> None:
    tok = get_installation_token_for_repo(
        work.owner,
        work.repo_name,
        github_installation_id=work.github_installation_id,
    )
    comment_on_issue(
        work.owner,
        work.repo_name,
        work.issue_number,
        tok,
        _insufficient_wallet_comment_body(),
    )


def notify_insufficient_wallet_for_pr(work: PROpenedForReview) -> None:
    tok = get_installation_token_for_repo(
        work.owner,
        work.repo_name,
        github_installation_id=work.github_installation_id,
    )
    comment_on_pr(
        work.owner,
        work.repo_name,
        work.pr_number,
        tok,
        _insufficient_wallet_comment_body(),
    )
