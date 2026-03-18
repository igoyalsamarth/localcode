"""GitHub connection management routes."""

from typing import Optional
from uuid import UUID
import os

import requests
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from constants import GITHUB_APP_SLUG, GITHUB_APP_ID, CLIENT_URL
from db import session_scope
from model.tables import User, Organization, GitHubInstallation
from logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("/github")
async def get_github_connection():
    """
    Get GitHub App installation status for the authenticated user's organization.
    
    Returns connection details if GitHub App is installed.
    
    TODO: Get user_id from JWT token or session
    """
    # TODO: Get user_id from authenticated session
    # For now, get the most recent user as a placeholder
    
    with session_scope() as session:
        stmt = select(User).order_by(User.created_at.desc()).limit(1)
        user = session.execute(stmt).scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found. Please authenticate first."
            )
        
        # Get user's organization
        stmt = select(Organization).where(Organization.owner_user_id == user.id)
        org = session.execute(stmt).scalar_one_or_none()
        
        if not org:
            return {
                "id": str(user.id),
                "connected": False,
            }
        
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
async def get_github_installation():
    """
    Get GitHub App installation details for the authenticated user's organization.
    
    Returns installation details including repositories and permissions.
    
    TODO: Get user_id from JWT token or session
    """
    # TODO: Get user_id from authenticated session
    with session_scope() as session:
        stmt = select(User).order_by(User.created_at.desc()).limit(1)
        user = session.execute(stmt).scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found. Please authenticate first."
            )
        
        # Get user's organization
        stmt = select(Organization).where(Organization.owner_user_id == user.id)
        org = session.execute(stmt).scalar_one_or_none()
        
        if not org:
            return {
                "id": str(user.id),
                "installed": False,
            }
        
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


@router.post("/github/install")
async def install_github_app():
    """
    Generate GitHub App installation URL.
    
    Returns the URL to redirect user to install the GitHub App.
    
    TODO: Get user_id from JWT token or session
    """
    if not GITHUB_APP_SLUG:
        raise HTTPException(
            status_code=500,
            detail="GITHUB_APP_SLUG not configured"
        )
    
    # TODO: Get user_id from authenticated session
    with session_scope() as session:
        stmt = select(User).order_by(User.created_at.desc()).limit(1)
        user = session.execute(stmt).scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found. Please authenticate first."
            )
        
        user_id = str(user.id)
    
    # State parameter to track which user is installing
    state = user_id
    
    # Generate GitHub App installation URL
    installation_url = (
        f"https://github.com/apps/{GITHUB_APP_SLUG}/installations/new"
        f"?state={state}"
    )
    
    logger.info(f"Generated GitHub App installation URL for user: {user_id}")
    
    return {
        "installUrl": installation_url,
    }


@router.get("/github/connect")
async def connect_github():
    """
    Alias for /github/install endpoint (GET method).
    
    Generate GitHub App installation URL.
    """
    return await install_github_app()


@router.get("/github/callback")
async def github_app_callback(
    installation_id: Optional[int] = Query(None),
    setup_action: Optional[str] = Query(None),
    state: Optional[str] = Query(None)
):
    """
    Handle GitHub App installation callback.
    
    Called by GitHub after user installs the app.
    Frontend should redirect here after installation.
    
    Args:
        installation_id: GitHub App installation ID
        setup_action: Action performed (install, update)
        state: State parameter containing user_id
    """
    redirect_url = f"{CLIENT_URL}/dashboard/connections"
    
    if not installation_id:
        logger.error("No installation_id provided in callback")
        return RedirectResponse(url=f"{redirect_url}?status=error&message=No installation ID")
    
    # Parse state to get user_id
    try:
        user_id = UUID(state) if state else None
    except (ValueError, AttributeError):
        logger.error(f"Invalid state parameter: {state}")
        return RedirectResponse(url=f"{redirect_url}?status=error&message=Invalid state")
    
    if not user_id:
        logger.error("No user_id in state parameter")
        return RedirectResponse(url=f"{redirect_url}?status=error&message=No user ID")
    
    try:
        with session_scope() as session:
            # Get user
            stmt = select(User).where(User.id == user_id)
            user = session.execute(stmt).scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            # Get user's organization
            stmt = select(Organization).where(Organization.owner_user_id == user.id)
            org = session.execute(stmt).scalar_one_or_none()
            
            if not org:
                raise HTTPException(status_code=404, detail="Organization not found")
            
            # Check if installation already exists
            stmt = select(GitHubInstallation).where(
                GitHubInstallation.github_installation_id == installation_id
            )
            installation = session.execute(stmt).scalar_one_or_none()
            
            if installation:
                logger.info(f"Updating existing GitHub installation: {installation_id}")
                installation.organization_id = org.id
            else:
                logger.info(f"Creating new GitHub installation: {installation_id}")
                installation = GitHubInstallation(
                    organization_id=org.id,
                    github_installation_id=installation_id,
                    account_name=user.github_login or "Unknown",
                )
                session.add(installation)
            
            # Update organization with installation ID
            org.github_installation_id = installation_id
            
            session.commit()
            
            logger.info(f"GitHub App installed for org: {org.name}, installation_id: {installation_id}")
        
        return RedirectResponse(url=f"{redirect_url}?status=connected")
        
    except Exception as e:
        logger.exception(f"Failed to process GitHub App installation: {e}")
        return RedirectResponse(url=f"{redirect_url}?status=error&message={str(e)}")


@router.delete("/github")
async def disconnect_github():
    """
    Disconnect GitHub App installation for the authenticated user's organization.
    
    TODO: Get user_id from JWT token or session
    """
    # TODO: Get user_id from authenticated session
    
    with session_scope() as session:
        stmt = select(User).order_by(User.created_at.desc()).limit(1)
        user = session.execute(stmt).scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )
        
        # Get user's organization
        stmt = select(Organization).where(Organization.owner_user_id == user.id)
        org = session.execute(stmt).scalar_one_or_none()
        
        if not org:
            raise HTTPException(
                status_code=404,
                detail="Organization not found"
            )
        
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
