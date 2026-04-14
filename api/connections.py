"""GitHub connection management routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.deps import get_current_org_id, get_current_user_id
from api.user_org import require_org_membership
from constants import GITHUB_APP_SLUG
from db import session_scope
from model.tables import User, Organization, GitHubInstallation
from logger import get_logger
from services.github.installation_sync import bind_installation_to_workspace
from task_queue.tasks import process_github_installation_repo_sync

logger = get_logger(__name__)

router = APIRouter(prefix="/connections", tags=["connections"])


class GitHubInstallationCallbackBody(BaseModel):
    installation_id: int = Field(..., ge=1)
    setup_action: str | None = None


@router.get("/github")
async def get_github_connection(
    user_id: UUID = Depends(get_current_user_id),
    org_id: UUID = Depends(get_current_org_id),
):
    """
    Get GitHub App installation status for the authenticated user's organization.

    Returns connection details if GitHub App is installed.
    """
    with session_scope() as session:
        user, org = require_org_membership(session, user_id, org_id)

        # Check if organization has GitHub App installation
        stmt = select(GitHubInstallation).where(
            GitHubInstallation.organization_id == org.id
        )
        installation = session.execute(stmt).scalar_one_or_none()

        if not installation:
            return {
                "id": str(user.id),
                "connected": False,
            }

        # GitHub App is installed
        return {
            "id": str(installation.id),
            "connected": True,
            "username": installation.account_name,
            "avatarUrl": user.avatar_url,
            "connectedAt": installation.created_at.isoformat() if installation.created_at else None,
            "scopes": ["repo", "contents", "pull_requests", "issues"],
        }


@router.get("/github/installation")
async def get_github_installation(
    user_id: UUID = Depends(get_current_user_id),
    org_id: UUID = Depends(get_current_org_id),
):
    """
    Get GitHub App installation details for the authenticated user's organization.

    Returns installation details including repositories and permissions.
    """
    with session_scope() as session:
        user, org = require_org_membership(session, user_id, org_id)

        # Check if organization has GitHub App installation
        stmt = select(GitHubInstallation).where(
            GitHubInstallation.organization_id == org.id
        )
        installation = session.execute(stmt).scalar_one_or_none()

        if not installation:
            return {
                "id": str(user.id),
                "installed": False,
            }

        # Get repositories for this organization
        from model.tables import Repository

        stmt = select(Repository).where(Repository.organization_id == org.id)
        repositories = session.execute(stmt).scalars().all()

        return {
            "id": str(installation.id),
            "installed": True,
            "accountLogin": installation.account_name,
            "accountType": installation.account_type or "Organization",
            "accountAvatarUrl": installation.account_avatar_url or user.avatar_url,
            "installedAt": installation.created_at.isoformat() if installation.created_at else None,
            "repositories": [
                {
                    "id": repo.github_repo_id,
                    "name": repo.name,
                    "fullName": f"{repo.owner}/{repo.name}",
                    "private": repo.private,
                }
                for repo in repositories
            ],
            "permissions": installation.permissions or {
                "contents": "write",
                "issues": "write",
                "pull_requests": "write",
                "metadata": "read",
            },
        }


def _github_app_install_response() -> dict:
    if not GITHUB_APP_SLUG:
        raise HTTPException(
            status_code=500,
            detail="GITHUB_APP_SLUG not configured",
        )
    installation_url = (
        f"https://github.com/apps/{GITHUB_APP_SLUG}/installations/new"
    )
    logger.info("Generated GitHub App installation URL (single workspace per user)")
    return {"installUrl": installation_url}


@router.post("/github/install")
async def install_github_app(
    user_id: UUID = Depends(get_current_user_id),
    org_id: UUID = Depends(get_current_org_id),
):
    """
    Generate GitHub App installation URL for the authenticated user's organization.
    """
    with session_scope() as session:
        require_org_membership(session, user_id, org_id)
    return _github_app_install_response()


@router.get("/github/connect")
async def connect_github(
    user_id: UUID = Depends(get_current_user_id),
    org_id: UUID = Depends(get_current_org_id),
):
    """
    Alias for /github/install endpoint (GET method).

    Generate GitHub App installation URL for the current organization.
    """
    with session_scope() as session:
        require_org_membership(session, user_id, org_id)
    return _github_app_install_response()


@router.post("/github/installation/callback")
async def github_installation_callback_api(
    body: GitHubInstallationCallbackBody,
    user_id: UUID = Depends(get_current_user_id),
    org_id: UUID = Depends(get_current_org_id),
):
    """
    Complete GitHub App installation (SPA callback).

    Frontend receives ``installation_id`` from GitHub's redirect and POSTs here with the
    session token. The installation is bound to the organization in the JWT (single workspace).
    """
    with session_scope() as session:
        user, org = require_org_membership(session, user_id, org_id)
        account_login = bind_installation_to_workspace(
            session,
            org=org,
            user=user,
            installation_id=body.installation_id,
        )
        org_id_str = str(org.id)
        logger.info(
            "GitHub App installed for workspace org=%s installation_id=%s",
            org.name,
            body.installation_id,
        )
    process_github_installation_repo_sync.send(
        org_id_str,
        body.installation_id,
        account_login,
    )
    return {"status": "connected"}


@router.delete("/github")
async def disconnect_github(
    user_id: UUID = Depends(get_current_user_id),
    org_id: UUID = Depends(get_current_org_id),
):
    """
    Disconnect GitHub App installation for the authenticated user's organization.
    """
    with session_scope() as session:
        user, org = require_org_membership(session, user_id, org_id)

        # Delete GitHub installation
        stmt = select(GitHubInstallation).where(
            GitHubInstallation.organization_id == org.id
        )
        installation = session.execute(stmt).scalar_one_or_none()

        if installation:
            session.delete(installation)

        # Clear organization installation ID
        org.github_installation_id = None

        session.commit()

        logger.info("GitHub App disconnected for org: %s", org.name)

        return {
            "status": "disconnected",
            "id": str(user.id),
            "connected": False,
        }
