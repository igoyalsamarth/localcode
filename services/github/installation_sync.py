"""Bind GitHub App installations to a GreAgent workspace and sync repositories."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from logger import get_logger
from model.tables import GitHubInstallation, Organization, User
from services.github.installation_token import (
    fetch_app_installation_json,
    get_api_token_for_installation,
    list_installation_repositories,
)
from services.github.repository_bootstrap import (
    ensure_default_coder_repository_agent,
    ensure_default_review_repository_agent,
    upsert_repository_from_github,
)
from services.github.coder_workflow import ensure_greagent_labels_on_repository
from services.github.review_workflow import ensure_greagent_review_labels_on_repository

logger = get_logger(__name__)


def clear_organization_installation_pointers_except(
    session: Session,
    installation_id: int,
    keep_org_id: UUID,
) -> None:
    """Remove ``github_installation_id`` from any org other than ``keep_org_id``."""
    stmt = select(Organization).where(Organization.github_installation_id == installation_id)
    for org in session.execute(stmt).scalars().all():
        if org.id != keep_org_id:
            org.github_installation_id = None


def _ensure_labels_for_repositories(
    installation_id: int,
    repositories: list[dict[str, Any]],
) -> None:
    try:
        install_tok = get_api_token_for_installation(int(installation_id))
    except Exception:
        logger.exception(
            "No installation token for labels (installation_id=%s)", installation_id
        )
        return
    for repo in repositories:
        full_name = repo.get("full_name") or ""
        if "/" not in full_name:
            continue
        owner, name = full_name.split("/", 1)
        try:
            ensure_greagent_labels_on_repository(owner, name, access_token=install_tok)
            ensure_greagent_review_labels_on_repository(owner, name, access_token=install_tok)
        except Exception:
            logger.exception("Failed to ensure greagent labels for %s", full_name)


def sync_repositories_from_webhook_payload(
    session: Session,
    organization_id: UUID,
    installation_id: int,
    repositories: list[dict[str, Any]],
    account_login_fallback: str | None,
) -> None:
    """Upsert repositories from a GitHub ``installation`` webhook ``repositories`` list."""
    for repo in repositories:
        try:
            row = upsert_repository_from_github(
                session,
                organization_id,
                repo,
                account_login_fallback=account_login_fallback,
            )
            ensure_default_coder_repository_agent(session, row)
            ensure_default_review_repository_agent(session, row)
        except Exception:
            logger.exception(
                "Failed to upsert repository from installation webhook: %s",
                repo.get("full_name"),
            )
    session.flush()
    _ensure_labels_for_repositories(installation_id, repositories)


def complete_installation_for_workspace(
    session: Session,
    *,
    org: Organization,
    user: User,
    installation_id: int,
) -> None:
    """
    Attach ``installation_id`` to ``org``, refresh account metadata from GitHub,
    and sync all accessible repositories via the installation token.
    """
    clear_organization_installation_pointers_except(session, installation_id, org.id)

    info = fetch_app_installation_json(installation_id)
    account = info.get("account") or {}
    account_login = account.get("login") or user.github_login or "Unknown"
    account_type = account.get("type")
    account_avatar_url = account.get("avatar_url")
    permissions = info.get("permissions")

    stmt = select(GitHubInstallation).where(
        GitHubInstallation.github_installation_id == installation_id
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row:
        row.organization_id = org.id
        row.account_name = account_login
        row.account_type = account_type
        row.account_avatar_url = account_avatar_url
        row.permissions = permissions
    else:
        row = GitHubInstallation(
            organization_id=org.id,
            github_installation_id=installation_id,
            account_name=account_login,
            account_type=account_type,
            account_avatar_url=account_avatar_url,
            permissions=permissions,
        )
        session.add(row)

    org.github_installation_id = installation_id
    session.flush()

    try:
        repos = list_installation_repositories(installation_id)
    except Exception:
        logger.exception(
            "Failed to list repositories for installation_id=%s", installation_id
        )
        repos = []

    for repo in repos:
        try:
            r = upsert_repository_from_github(
                session,
                org.id,
                repo,
                account_login_fallback=account_login,
            )
            ensure_default_coder_repository_agent(session, r)
            ensure_default_review_repository_agent(session, r)
        except Exception:
            logger.exception(
                "Failed to upsert repository from installation API: %s",
                repo.get("full_name"),
            )
    session.flush()
    _ensure_labels_for_repositories(installation_id, repos)
