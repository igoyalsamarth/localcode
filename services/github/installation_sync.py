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
    *,
    apply_labels: bool = True,
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
    if apply_labels:
        _ensure_labels_for_repositories(installation_id, repositories)


def bind_installation_to_workspace(
    session: Session,
    *,
    org: Organization,
    user: User,
    installation_id: int,
) -> str:
    """
    Persist GitHub installation metadata and attach it to ``org`` (no repository listing).

    Repository upserts and label setup run in a background worker via
    :func:`sync_installation_repositories_from_github_api` so HTTP handlers stay fast.
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
    return str(account_login)


def sync_installation_repositories_from_github_api(
    session: Session,
    *,
    organization_id: UUID,
    installation_id: int,
    account_login_fallback: str | None,
) -> None:
    """
    List all installation-visible repositories from GitHub, upsert DB rows, ensure agents,
    then apply GreAgent labels on each repo.

    Intended to run inside a worker session after :func:`bind_installation_to_workspace`
    has committed.
    """
    org = session.get(Organization, organization_id)
    if org is None:
        logger.warning(
            "installation repo sync skipped: organization %s not found",
            organization_id,
        )
        return
    if org.github_installation_id != installation_id:
        logger.warning(
            "installation repo sync skipped: org %s has installation_id=%s (expected %s)",
            organization_id,
            org.github_installation_id,
            installation_id,
        )
        return

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
                organization_id,
                repo,
                account_login_fallback=account_login_fallback,
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


def complete_installation_for_workspace(
    session: Session,
    *,
    org: Organization,
    user: User,
    installation_id: int,
) -> None:
    """
    Attach ``installation_id`` to ``org`` and synchronously sync all repositories.

    Prefer binding in the API layer and enqueueing
    :func:`task_queue.tasks.process_github_installation_repo_sync` for large installs;
    this function remains for tests and one-shot tooling.
    """
    account_login = bind_installation_to_workspace(
        session, org=org, user=user, installation_id=installation_id
    )
    sync_installation_repositories_from_github_api(
        session,
        organization_id=org.id,
        installation_id=installation_id,
        account_login_fallback=account_login,
    )
