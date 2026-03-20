"""Unified GitHub webhook: App installation + issues (coder agent)."""

import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from sqlalchemy import select

from db import session_scope
from logger import get_logger
from model.tables import User, Organization, GitHubInstallation
from services.github.coder_workflow import (
    prepare_issue_for_coder_work,
    run_coder_agent_for_opened_issue,
)
from services.github.issue_payload import IssueOpenedForCoder
from services.github.webhook_signature import verify_github_webhook_signature

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

                    session.commit()
                    logger.info(
                        "GitHub App installation stored for org: %s with %s repositories",
                        org.name,
                        len(repositories),
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

    logger.info(
        "GitHub App repositories event: %s, installation_id: %s",
        action,
        installation_id,
    )

    return {
        "status": "received",
        "action": action,
        "installation_id": installation_id,
    }


def _parse_coder_trigger(data: dict[str, Any]) -> IssueOpenedForCoder | None:
    return IssueOpenedForCoder.from_issues_webhook(data)


async def _handle_issues_event(
    data: dict[str, Any],
    background_tasks: BackgroundTasks,
    x_github_delivery: str | None,
) -> dict[str, Any]:
    work = _parse_coder_trigger(data)

    if work is None:
        action = data.get("action")
        logger.info(
            "Ignoring issues event (not a coder trigger): action=%s", action
        )
        return {"status": "ignored", "action": action}

    logger.info(
        "Coder webhook delivery=%s action=%s issue=%s#%s",
        x_github_delivery,
        data.get("action"),
        work.full_name,
        work.issue_number,
    )

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
        "Coder triggered for issue #%s %s in %s",
        work.issue_number,
        work.issue_title,
        work.full_name,
    )

    background_tasks.add_task(run_coder_agent_for_opened_issue, work)

    return {
        "status": "received",
        "issue_number": work.issue_number,
        "issue_title": work.issue_title,
        "repository": work.full_name,
    }


@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
):
    """
    Single endpoint for GitHub webhooks (GitHub App or repository).

    - ``installation`` / ``installation_repositories``: persist installation and repos.
    - ``issues``: ``greagent:code`` label → coder agent (labels, PR, comment).
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
        return await _handle_issues_event(data, background_tasks, x_github_delivery)

    logger.info("Ignoring GitHub event: %s", x_github_event)
    return {"status": "ignored", "event": x_github_event}
