"""GitHub connection management routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.deps import get_current_user_id
from api.user_org import require_user_and_owned_org
from constants import GITHUB_APP_SLUG
from db import session_scope
from model.tables import User, Organization, GitHubInstallation
from logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/connections", tags=["connections"])


def _persist_github_installation(
    session,
    *,
    user: User,
    org: Organization,
    installation_id: int,
) -> None:
    stmt = select(GitHubInstallation).where(
        GitHubInstallation.github_installation_id == installation_id
    )
    installation = session.execute(stmt).scalar_one_or_none()

    if installation:
        logger.info("Updating existing GitHub installation: %s", installation_id)
        installation.organization_id = org.id
    else:
        logger.info("Creating new GitHub installation: %s", installation_id)
        installation = GitHubInstallation(
            organization_id=org.id,
            github_installation_id=installation_id,
            account_name=user.github_login or "Unknown",
        )
        session.add(installation)

    org.github_installation_id = installation_id


class GitHubInstallationCallbackBody(BaseModel):
    installation_id: int = Field(..., ge=1)
    setup_action: str | None = None


@router.get("/github")
async def get_github_connection(user_id: UUID = Depends(get_current_user_id)):
    """
    Get GitHub App installation status for the authenticated user's organization.

    Returns connection details if GitHub App is installed.
    """
    with session_scope() as session:
        user, org = require_user_and_owned_org(session, user_id)

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
async def get_github_installation(user_id: UUID = Depends(get_current_user_id)):
    """
    Get GitHub App installation details for the authenticated user's organization.

    Returns installation details including repositories and permissions.
    """
    with session_scope() as session:
        user, org = require_user_and_owned_org(session, user_id)

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
        
        # GitHub App is installed - return full details
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


def _github_app_install_response(user_id: UUID) -> dict:
    if not GITHUB_APP_SLUG:
        raise HTTPException(
            status_code=500,
            detail="GITHUB_APP_SLUG not configured",
        )
    state = str(user_id)
    installation_url = (
        f"https://github.com/apps/{GITHUB_APP_SLUG}/installations/new"
        f"?state={state}"
    )
    logger.info("Generated GitHub App installation URL for user: %s", state)
    return {"installUrl": installation_url}


@router.post("/github/install")
async def install_github_app(user_id: UUID = Depends(get_current_user_id)):
    """
    Generate GitHub App installation URL.

    Returns the URL to redirect user to install the GitHub App.
    """
    with session_scope() as session:
        require_user_and_owned_org(session, user_id)
    return _github_app_install_response(user_id)


@router.get("/github/connect")
async def connect_github(user_id: UUID = Depends(get_current_user_id)):
    """
    Alias for /github/install endpoint (GET method).

    Generate GitHub App installation URL.
    """
    with session_scope() as session:
        require_user_and_owned_org(session, user_id)
    return _github_app_install_response(user_id)


@router.post("/github/installation/callback")
async def github_installation_callback_api(
    body: GitHubInstallationCallbackBody,
    user_id: UUID = Depends(get_current_user_id),
):
    """
    Complete GitHub App installation (SPA callback).

    Frontend receives ``installation_id`` from GitHub redirect and POSTs here with
    a Bearer session token.
    """
    with session_scope() as session:
        user, org = require_user_and_owned_org(session, user_id)
        _persist_github_installation(
            session,
            user=user,
            org=org,
            installation_id=body.installation_id,
        )
        session.commit()
        logger.info(
            "GitHub App installed via API for org: %s, installation_id: %s",
            org.name,
            body.installation_id,
        )
    return {"status": "connected"}


@router.delete("/github")
async def disconnect_github(user_id: UUID = Depends(get_current_user_id)):
    """
    Disconnect GitHub App installation for the authenticated user's organization.
    """
    with session_scope() as session:
        user, org = require_user_and_owned_org(session, user_id)

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
        
        logger.info(f"GitHub App disconnected for org: {org.name}")
        
        return {
            "status": "disconnected",
            "id": str(user.id),
            "connected": False,
        }
