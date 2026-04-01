"""Unified GitHub webhook: App installation, issue workflow, and PR review workflow."""

import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select

from db import session_scope
from logger import get_logger
from model.tables import User, Organization, GitHubInstallation
from services.github.coder_trigger import resolve_coder_issue_work
from services.github.coder_workflow import (
    ensure_greagent_labels_on_repository,
    prepare_issue_for_coder_work,
)
from services.github.review_trigger import resolve_review_pr_work
from services.github.review_workflow import (
    ensure_greagent_review_labels_on_repository,
    prepare_pr_for_review_work,
)
from services.github.issue_payload import IssueOpenedForCoder
from services.github.pr_payload import PROpenedForReview
from services.github.installation_token import get_api_token_for_installation
from services.github.repository_bootstrap import (
    ensure_default_coder_repository_agent,
    ensure_default_review_repository_agent,
    upsert_repository_from_github,
)
from services.github.webhook_signature import verify_github_webhook_signature
from services.github.agent_wallet_gate import (
    notify_insufficient_wallet_for_issue,
    notify_insufficient_wallet_for_pr,
)
from services.wallet import wallet_allows_agent_run
from task_queue.tasks import process_github_issue, process_github_pr_review

logger = get_logger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhooks"])


def _installation_created(data: dict[str, Any]) -> dict[str, Any]:
    installation = data.get("installation", {})
    installation_id = installation.get("id")
    account = installation.get("account", {})
    account_login = account.get("login")
    action = data.get("action")

    account_type = account.get("type")
    account_avatar_url = account.get("avatar_url")
    permissions = installation.get("permissions", {})
    repositories = data.get("repositories", [])

    logger.info(
        "GitHub App installed by: %s, installation_id: %s, type: %s",
        account_login,
        installation_id,
        account_type,
    )

    with session_scope() as session:
        stmt = select(User).where(User.github_login == account_login)
        user = session.execute(stmt).scalar_one_or_none()

        if user:
            stmt = select(Organization).where(Organization.owner_user_id == user.id)
            org = session.execute(stmt).scalar_one_or_none()

            if org:
                stmt = select(GitHubInstallation).where(
                    GitHubInstallation.github_installation_id == installation_id
                )
                existing = session.execute(stmt).scalar_one_or_none()

                if not existing:
                    installation_record = GitHubInstallation(
                        organization_id=org.id,
                        github_installation_id=installation_id,
                        account_name=account_login,
                        account_type=account_type,
                        account_avatar_url=account_avatar_url,
                        permissions=permissions,
                    )
                    session.add(installation_record)
                    org.github_installation_id = installation_id

                    from model.tables import Repository

                    for repo in repositories:
                        repo_id = repo.get("id")
                        repo_name = repo.get("name")
                        repo_full_name = repo.get("full_name")
                        repo_private = repo.get("private", False)
                        repo_default_branch = repo.get("default_branch", "main")

                        stmt = select(Repository).where(
                            Repository.organization_id == org.id,
                            Repository.github_repo_id == repo_id,
                        )
                        existing_repo = session.execute(stmt).scalar_one_or_none()

                        if not existing_repo:
                            owner = (
                                repo_full_name.split("/")[0]
                                if repo_full_name and "/" in repo_full_name
                                else account_login
                            )
                            new_repo = Repository(
                                organization_id=org.id,
                                github_repo_id=repo_id,
                                name=repo_name,
                                owner=owner,
                                private=repo_private,
                                default_branch=repo_default_branch,
                                active=True,
                            )
                            session.add(new_repo)
                            session.flush()
                            ensure_default_coder_repository_agent(session, new_repo)
                            ensure_default_review_repository_agent(session, new_repo)
                        else:
                            ensure_default_coder_repository_agent(
                                session, existing_repo
                            )
                            ensure_default_review_repository_agent(
                                session, existing_repo
                            )

                    session.commit()
                    logger.info(
                        "GitHub App installation stored for org: %s with %s repositories",
                        org.name,
                        len(repositories),
                    )
                    try:
                        install_tok = get_api_token_for_installation(
                            int(installation_id)
                        )
                    except Exception:
                        install_tok = None
                        logger.exception(
                            "No installation token for labels (installation_id=%s)",
                            installation_id,
                        )
                    if install_tok:
                        for repo in repositories:
                            full_name = repo.get("full_name") or ""
                            if "/" not in full_name:
                                continue
                            owner, name = full_name.split("/", 1)
                            try:
                                ensure_greagent_labels_on_repository(
                                    owner, name, access_token=install_tok
                                )
                                ensure_greagent_review_labels_on_repository(
                                    owner, name, access_token=install_tok
                                )
                            except Exception:
                                logger.exception(
                                    "Failed to ensure greagent labels for %s", full_name
                                )
                else:
                    logger.info(
                        "GitHub App installation already exists: %s", installation_id
                    )
            else:
                logger.warning("No organization found for user: %s", account_login)
        else:
            logger.warning("No user found with GitHub login: %s", account_login)

    return {
        "status": "received",
        "action": action,
        "installation_id": installation_id,
    }


def _installation_deleted(data: dict[str, Any]) -> dict[str, Any]:
    installation = data.get("installation", {})
    installation_id = installation.get("id")
    action = data.get("action")

    with session_scope() as session:
        stmt = select(GitHubInstallation).where(
            GitHubInstallation.github_installation_id == installation_id
        )
        installation_record = session.execute(stmt).scalar_one_or_none()

        if installation_record:
            session.delete(installation_record)
            session.commit()
            logger.info("GitHub App installation deleted: %s", installation_id)

    return {
        "status": "received",
        "action": action,
        "installation_id": installation_id,
    }


def _handle_installation_event(data: dict[str, Any]) -> dict[str, Any]:
    action = data.get("action")
    installation = data.get("installation", {})
    installation_id = installation.get("id")

    logger.info(
        "GitHub App installation event: %s, installation_id: %s",
        action,
        installation_id,
    )

    if action == "created":
        return _installation_created(data)
    if action == "deleted":
        return _installation_deleted(data)

    return {"status": "ignored", "event": "installation", "action": action}


def _handle_installation_repositories(data: dict[str, Any]) -> dict[str, Any]:
    action = data.get("action")
    installation = data.get("installation", {})
    installation_id = installation.get("id")
    account = installation.get("account") or {}
    account_login = account.get("login")

    logger.info(
        "GitHub App repositories event: %s, installation_id: %s",
        action,
        installation_id,
    )

    repos_added = data.get("repositories_added") or []

    if action == "added" and repos_added:
        with session_scope() as session:
            stmt = select(GitHubInstallation).where(
                GitHubInstallation.github_installation_id == installation_id
            )
            inst = session.execute(stmt).scalar_one_or_none()
            if inst:
                for repo in repos_added:
                    try:
                        row = upsert_repository_from_github(
                            session,
                            inst.organization_id,
                            repo,
                            account_login_fallback=account_login,
                        )
                        ensure_default_coder_repository_agent(session, row)
                        ensure_default_review_repository_agent(session, row)
                    except Exception:
                        logger.exception(
                            "Failed to upsert repository from installation_repositories: %s",
                            repo.get("full_name"),
                        )
            else:
                logger.warning(
                    "installation_repositories added but no DB row for installation_id=%s",
                    installation_id,
                )

        try:
            install_tok = get_api_token_for_installation(int(installation_id))
        except Exception:
            install_tok = None
            logger.exception(
                "No installation token for labels (installation_id=%s)", installation_id
            )
        if install_tok:
            for repo in repos_added:
                full_name = repo.get("full_name") or ""
                if "/" not in full_name:
                    continue
                owner, name = full_name.split("/", 1)
                try:
                    ensure_greagent_labels_on_repository(
                        owner, name, access_token=install_tok
                    )
                    ensure_greagent_review_labels_on_repository(
                        owner, name, access_token=install_tok
                    )
                except Exception:
                    logger.exception(
                        "Failed to ensure greagent labels for %s", full_name
                    )

    return {
        "status": "received",
        "action": action,
        "installation_id": installation_id,
    }


def _parse_coder_trigger(data: dict[str, Any]) -> IssueOpenedForCoder | None:
    with session_scope() as session:
        return resolve_coder_issue_work(session, data)


def _parse_review_trigger(data: dict[str, Any]) -> PROpenedForReview | None:
    with session_scope() as session:
        return resolve_review_pr_work(session, data)


async def _handle_issues_event(
    data: dict[str, Any],
    x_github_delivery: str | None,
) -> dict[str, Any]:
    work = _parse_coder_trigger(data)

    if work is None:
        action = data.get("action")
        logger.info("Ignoring issues event (not a coder trigger): action=%s", action)
        return {"status": "ignored", "action": action}

    logger.info(
        "Coder webhook delivery=%s action=%s issue=%s#%s",
        x_github_delivery,
        data.get("action"),
        work.full_name,
        work.issue_number,
    )

    with session_scope() as session:
        if not wallet_allows_agent_run(session, work.owner, work.repo_name):
            logger.info(
                "Skipping coder enqueue (wallet below $2) for %s#%s",
                work.full_name,
                work.issue_number,
            )
            try:
                notify_insufficient_wallet_for_issue(work)
            except Exception:
                logger.exception(
                    "Failed to post insufficient-wallet comment on %s#%s",
                    work.full_name,
                    work.issue_number,
                )
            return {
                "status": "insufficient_wallet",
                "detail": "Organization wallet is below $2.00 USD; top up in billing settings.",
                "repository": work.full_name,
                "issue_number": work.issue_number,
            }

    try:
        prepare_issue_for_coder_work(work)
    except Exception:
        logger.exception(
            "prepare_issue_for_coder_work failed for %s#%s (delivery=%s)",
            work.full_name,
            work.issue_number,
            x_github_delivery,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to prepare issue (labels/reaction). Check token permissions.",
        ) from None

    logger.info(
        "Enqueuing coder task for issue #%s %s in %s",
        work.issue_number,
        work.issue_title,
        work.full_name,
    )

    issue_data = {
        "owner": work.owner,
        "repo_name": work.repo_name,
        "repo_url": work.repo_url,
        "full_name": work.full_name,
        "github_repo_id": work.github_repo_id,
        "issue_number": work.issue_number,
        "issue_title": work.issue_title,
        "issue_body": work.issue_body,
        "github_installation_id": work.github_installation_id,
    }

    process_github_issue.send(issue_data)

    return {
        "status": "enqueued",
        "issue_number": work.issue_number,
        "issue_title": work.issue_title,
        "repository": work.full_name,
    }


async def _handle_pull_request_event(
    data: dict[str, Any],
    x_github_delivery: str | None,
) -> dict[str, Any]:
    work = _parse_review_trigger(data)

    if work is None:
        action = data.get("action")
        logger.info("Ignoring pull_request event (not a review trigger): action=%s", action)
        return {"status": "ignored", "action": action}

    logger.info(
        "Review webhook delivery=%s action=%s pr=%s#%s",
        x_github_delivery,
        data.get("action"),
        work.full_name,
        work.pr_number,
    )

    with session_scope() as session:
        if not wallet_allows_agent_run(session, work.owner, work.repo_name):
            logger.info(
                "Skipping review enqueue (wallet below $2) for %s#%s",
                work.full_name,
                work.pr_number,
            )
            try:
                notify_insufficient_wallet_for_pr(work)
            except Exception:
                logger.exception(
                    "Failed to post insufficient-wallet comment on %s#%s",
                    work.full_name,
                    work.pr_number,
                )
            return {
                "status": "insufficient_wallet",
                "detail": "Organization wallet is below $2.00 USD; top up in billing settings.",
                "repository": work.full_name,
                "pr_number": work.pr_number,
            }

    try:
        prepare_pr_for_review_work(work)
    except Exception:
        logger.exception(
            "prepare_pr_for_review_work failed for %s#%s (delivery=%s)",
            work.full_name,
            work.pr_number,
            x_github_delivery,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to prepare PR (labels). Check token permissions.",
        ) from None

    logger.info(
        "Enqueuing review task for PR #%s %s in %s",
        work.pr_number,
        work.pr_title,
        work.full_name,
    )

    pr_data = {
        "owner": work.owner,
        "repo_name": work.repo_name,
        "repo_url": work.repo_url,
        "full_name": work.full_name,
        "github_repo_id": work.github_repo_id,
        "pr_number": work.pr_number,
        "pr_title": work.pr_title,
        "pr_body": work.pr_body,
        "base_branch": work.base_branch,
        "head_branch": work.head_branch,
        "head_sha": work.head_sha,
        "github_installation_id": work.github_installation_id,
    }

    process_github_pr_review.send(pr_data)

    return {
        "status": "enqueued",
        "pr_number": work.pr_number,
        "pr_title": work.pr_title,
        "repository": work.full_name,
    }


@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
):
    """
    Single endpoint for GitHub webhooks (GitHub App or repository).

    - ``installation`` / ``installation_repositories``: persist installation and repos.
    - ``issues``: enqueue coder task on the shared ``github_agent`` Dramatiq queue.
    - ``pull_request``: enqueue review task on the same ``github_agent`` queue.
    """
    payload = await request.body()

    if not verify_github_webhook_signature(payload, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    data: dict[str, Any] = json.loads(payload)

    if x_github_event == "installation":
        return _handle_installation_event(data)

    if x_github_event == "installation_repositories":
        return _handle_installation_repositories(data)

    if x_github_event == "issues":
        return await _handle_issues_event(data, x_github_delivery)

    if x_github_event == "pull_request":
        return await _handle_pull_request_event(data, x_github_delivery)

    logger.info("Ignoring GitHub event: %s", x_github_event)
    return {"status": "ignored", "event": x_github_event}
