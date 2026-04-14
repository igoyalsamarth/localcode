"""Unified GitHub webhook: App installation, issue workflow, and PR review workflow."""

import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select

from db import session_scope
from logger import get_logger
from model.tables import GitHubInstallation, Organization, User
from services.github.coder_trigger import (
    resolve_coder_issue_work,
    resolve_coder_pr_work,
)
from services.github.coder_workflow import (
    prepare_issue_for_coder_work,
    prepare_pr_for_coder_work,
)
from services.github.review_trigger import resolve_review_pr_work
from services.github.review_workflow import prepare_pr_for_review_work
from services.github.issue_payload import IssueOpenedForCoder
from services.github.pr_payload import PROpenedForReview
from services.github.installation_sync import bind_installation_to_workspace
from services.user_service import get_organization_for_user
from services.github.webhook_signature import verify_github_webhook_signature
from services.github.agent_wallet_gate import (
    notify_insufficient_wallet_for_issue,
    notify_insufficient_wallet_for_pr,
)
from services.wallet import wallet_allows_agent_run
from task_queue.tasks import (
    process_github_installation_repo_sync,
    process_github_issue,
    process_github_pr_coder,
    process_github_pr_review,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhooks"])


def _installation_created(data: dict[str, Any]) -> dict[str, Any]:
    """
    GitHub sends this before the user returns to our SPA.

    We attach the installation to the GreAgent user identified by ``sender`` or installation
    ``account`` login (must match ``users.github_login``). The SPA callback remains for
    idempotent completion when the webhook could not resolve the user yet.
    """
    installation = data.get("installation", {})
    installation_id = installation.get("id")
    if installation_id is None:
        return {"status": "ignored", "event": "installation", "reason": "missing_installation_id"}
    account = installation.get("account", {})
    account_login = account.get("login")
    action = data.get("action")
    account_type = account.get("type")
    account_avatar_url = account.get("avatar_url")
    permissions = installation.get("permissions", {})
    repositories = data.get("repositories") or []
    sender = data.get("sender") or {}
    sender_login = sender.get("login")

    logger.info(
        "GitHub App installation.created: account=%s installation_id=%s type=%s",
        account_login,
        installation_id,
        account_type,
    )

    ignored: dict[str, Any] | None = None
    repo_sync_job: tuple[str, int, str | None] | None = None

    with session_scope() as session:
        stmt = select(GitHubInstallation).where(
            GitHubInstallation.github_installation_id == installation_id
        )
        existing = session.execute(stmt).scalar_one_or_none()

        if not existing:
            login = sender_login or account_login
            user = None
            if login:
                user = session.execute(
                    select(User).where(User.github_login == login)
                ).scalar_one_or_none()
            if not user and account_login and account_login != login:
                user = session.execute(
                    select(User).where(User.github_login == account_login)
                ).scalar_one_or_none()

            org = get_organization_for_user(session, user.id) if user else None
            if not user or not org:
                logger.warning(
                    "installation.created ignored: no GreAgent user/org for "
                    "installation_id=%s sender=%s account=%s",
                    installation_id,
                    sender_login,
                    account_login,
                )
                ignored = {
                    "status": "ignored",
                    "event": "installation",
                    "reason": "unknown_installer",
                    "installation_id": installation_id,
                }
            else:
                account_login_bound = bind_installation_to_workspace(
                    session,
                    org=org,
                    user=user,
                    installation_id=int(installation_id),
                )
                repo_sync_job = (
                    str(org.id),
                    int(installation_id),
                    account_login_bound,
                )
        else:
            existing.account_name = account_login or existing.account_name
            existing.account_type = account_type or existing.account_type
            existing.account_avatar_url = account_avatar_url or existing.account_avatar_url
            existing.permissions = permissions or existing.permissions

            if repositories:
                repo_sync_job = (
                    str(existing.organization_id),
                    int(installation_id),
                    account_login,
                )

    if ignored is not None:
        return ignored
    if repo_sync_job is not None:
        process_github_installation_repo_sync.send(*repo_sync_job)

    return {
        "status": "received",
        "action": action,
        "installation_id": installation_id,
    }


def _installation_deleted(data: dict[str, Any]) -> dict[str, Any]:
    installation = data.get("installation", {})
    installation_id = installation.get("id")
    action = data.get("action")
    if installation_id is None:
        return {"status": "ignored", "event": "installation", "reason": "missing_installation_id"}

    with session_scope() as session:
        stmt = select(GitHubInstallation).where(
            GitHubInstallation.github_installation_id == installation_id
        )
        installation_record = session.execute(stmt).scalar_one_or_none()

        if installation_record:
            org_id = installation_record.organization_id
            session.delete(installation_record)
            org = session.get(Organization, org_id)
            if org is not None and org.github_installation_id == installation_id:
                org.github_installation_id = None
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

    if action == "added" and repos_added and installation_id is not None:
        org_id_str: str | None = None
        with session_scope() as session:
            stmt = select(GitHubInstallation).where(
                GitHubInstallation.github_installation_id == installation_id
            )
            inst = session.execute(stmt).scalar_one_or_none()
            if inst:
                org_id_str = str(inst.organization_id)
            else:
                logger.warning(
                    "installation_repositories.added before installation row exists "
                    "(installation_id=%s); callback or installation.created will sync repos",
                    installation_id,
                )
        if org_id_str is not None:
            login_for_sync = account_login if isinstance(account_login, str) else None
            process_github_installation_repo_sync.send(
                org_id_str,
                int(installation_id),
                login_for_sync,
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


def _parse_coder_pr_trigger(data: dict[str, Any]) -> PROpenedForReview | None:
    with session_scope() as session:
        return resolve_coder_pr_work(session, data)


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
        if not wallet_allows_agent_run(
            session,
            work.owner,
            work.repo_name,
            github_installation_id=work.github_installation_id,
            github_repo_id=work.github_repo_id,
        ):
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
        "github_sender_login": work.github_sender_login,
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
    coder_work = _parse_coder_pr_trigger(data)
    if coder_work is not None:
        logger.info(
            "PR coder webhook delivery=%s action=%s pr=%s#%s",
            x_github_delivery,
            data.get("action"),
            coder_work.full_name,
            coder_work.pr_number,
        )
        with session_scope() as session:
            if not wallet_allows_agent_run(
                session,
                coder_work.owner,
                coder_work.repo_name,
                github_installation_id=coder_work.github_installation_id,
                github_repo_id=coder_work.github_repo_id,
            ):
                logger.info(
                    "Skipping PR coder enqueue (wallet below $2) for %s#%s",
                    coder_work.full_name,
                    coder_work.pr_number,
                )
                try:
                    notify_insufficient_wallet_for_pr(coder_work)
                except Exception:
                    logger.exception(
                        "Failed to post insufficient-wallet comment on %s#%s",
                        coder_work.full_name,
                        coder_work.pr_number,
                    )
                return {
                    "status": "insufficient_wallet",
                    "detail": "Organization wallet is below $2.00 USD; top up in billing settings.",
                    "repository": coder_work.full_name,
                    "pr_number": coder_work.pr_number,
                }
        try:
            prepare_pr_for_coder_work(coder_work)
        except Exception:
            logger.exception(
                "prepare_pr_for_coder_work failed for %s#%s (delivery=%s)",
                coder_work.full_name,
                coder_work.pr_number,
                x_github_delivery,
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to prepare PR for coder (labels/reaction). Check token permissions.",
            ) from None
        logger.info(
            "Enqueuing PR coder task for #%s %s in %s",
            coder_work.pr_number,
            coder_work.pr_title,
            coder_work.full_name,
        )
        pr_data = {
            "owner": coder_work.owner,
            "repo_name": coder_work.repo_name,
            "repo_url": coder_work.repo_url,
            "full_name": coder_work.full_name,
            "github_repo_id": coder_work.github_repo_id,
            "pr_number": coder_work.pr_number,
            "pr_title": coder_work.pr_title,
            "pr_body": coder_work.pr_body,
            "base_branch": coder_work.base_branch,
            "head_branch": coder_work.head_branch,
            "head_sha": coder_work.head_sha,
            "github_installation_id": coder_work.github_installation_id,
            "github_sender_login": coder_work.github_sender_login,
        }
        process_github_pr_coder.send(pr_data)
        return {
            "status": "enqueued",
            "workflow": "pr_coder",
            "pr_number": coder_work.pr_number,
            "pr_title": coder_work.pr_title,
            "repository": coder_work.full_name,
        }

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
        if not wallet_allows_agent_run(
            session,
            work.owner,
            work.repo_name,
            github_installation_id=work.github_installation_id,
            github_repo_id=work.github_repo_id,
        ):
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
        "base_sha": work.base_sha,
        "github_installation_id": work.github_installation_id,
        "github_sender_login": work.github_sender_login,
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
    - ``pull_request``: enqueue review task, or PR coder when label ``greagent:code`` is added.
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
