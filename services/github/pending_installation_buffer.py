"""Buffer GitHub install webhook data until the SPA callback binds a workspace."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from logger import get_logger
from model.tables import PendingGitHubInstallation

logger = get_logger(__name__)


def merge_repository_payloads(*lists: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Deduplicate GitHub repository objects by numeric ``id``."""
    seen: dict[int, dict[str, Any]] = {}
    for lst in lists:
        if not lst:
            continue
        for repo in lst:
            if not isinstance(repo, dict):
                continue
            rid = repo.get("id")
            if rid is None:
                continue
            try:
                seen[int(rid)] = repo
            except (TypeError, ValueError):
                continue
    return list(seen.values())


def record_pending_installation_created(
    session: Session,
    *,
    installation_id: int,
    sender_login: str | None,
    account_login: str | None,
    account_type: str | None,
    account_avatar_url: str | None,
    permissions: dict[str, Any] | None,
    repositories: list[dict[str, Any]] | None,
) -> None:
    """Upsert pending row from ``installation`` webhook (``action`` = ``created``)."""
    row = session.get(PendingGitHubInstallation, installation_id)
    merged_repos = merge_repository_payloads(
        row.repositories_json if row and row.repositories_json else None,
        repositories,
    )
    if row is None:
        row = PendingGitHubInstallation(
            github_installation_id=installation_id,
            sender_login=sender_login,
            account_login=account_login,
            account_type=account_type,
            account_avatar_url=account_avatar_url,
            permissions=permissions,
            repositories_json=merged_repos or None,
        )
        session.add(row)
    else:
        if sender_login:
            row.sender_login = sender_login
        if account_login:
            row.account_login = account_login
        if account_type:
            row.account_type = account_type
        if account_avatar_url:
            row.account_avatar_url = account_avatar_url
        if permissions is not None:
            row.permissions = permissions
        row.repositories_json = merged_repos or None
    session.flush()
    logger.info(
        "Buffered pending GitHub install installation_id=%s repos=%s",
        installation_id,
        len(merged_repos),
    )


def merge_pending_repositories_added(
    session: Session,
    installation_id: int,
    repos_added: list[dict[str, Any]],
    *,
    account_login: str | None,
) -> None:
    """Append ``repositories_added`` from ``installation_repositories`` webhook."""
    if not repos_added:
        return
    row = session.get(PendingGitHubInstallation, installation_id)
    if row is None:
        row = PendingGitHubInstallation(
            github_installation_id=installation_id,
            account_login=account_login,
            repositories_json=merge_repository_payloads(repos_added),
        )
        session.add(row)
    else:
        row.repositories_json = merge_repository_payloads(row.repositories_json, repos_added)
        if account_login and not row.account_login:
            row.account_login = account_login
    session.flush()
    logger.info(
        "Merged installation_repositories into pending installation_id=%s total_repos=%s",
        installation_id,
        len(row.repositories_json or []),
    )


def delete_pending_if_exists(session: Session, installation_id: int) -> None:
    row = session.get(PendingGitHubInstallation, installation_id)
    if row is not None:
        session.delete(row)
        session.flush()
