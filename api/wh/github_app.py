"""GitHub App installation webhook handler."""

import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select

from constants import GITHUB_WEBHOOK_SECRET
from db import session_scope
from model.tables import User, Organization, GitHubInstallation
from logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhooks"])


def _verify_signature(payload: bytes, signature: str | None) -> bool:
    """Verify the GitHub webhook signature using HMAC-SHA256."""
    if not GITHUB_WEBHOOK_SECRET:
        logger.warning(
            "GITHUB_WEBHOOK_SECRET not set - skipping signature verification"
        )
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


@router.post("/github-app")
async def github_app_webhook(
    request: Request,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
):
    """
    Receive GitHub App webhooks for installation events.
    
    Handles:
    - installation (created, deleted)
    - installation_repositories (added, removed)
    """
    payload = await request.body()

    if not _verify_signature(payload, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    data: dict[str, Any] = json.loads(payload)
    
    # Handle installation events
    if x_github_event == "installation":
        action = data.get("action")
        installation = data.get("installation", {})
        installation_id = installation.get("id")
        account = installation.get("account", {})
        account_login = account.get("login")
        
        logger.info(f"GitHub App installation event: {action}, installation_id: {installation_id}")
        
        if action == "created":
            account_type = account.get("type")
            account_avatar_url = account.get("avatar_url")
            permissions = installation.get("permissions", {})
            repositories = data.get("repositories", [])
            
            logger.info(f"GitHub App installed by: {account_login}, installation_id: {installation_id}, type: {account_type}")
            
            # Try to find matching user by GitHub login
            with session_scope() as session:
                stmt = select(User).where(User.github_login == account_login)
                user = session.execute(stmt).scalar_one_or_none()
                
                if user:
                    # Get user's organization
                    stmt = select(Organization).where(Organization.owner_user_id == user.id)
                    org = session.execute(stmt).scalar_one_or_none()
                    
                    if org:
                        # Check if installation already exists
                        stmt = select(GitHubInstallation).where(
                            GitHubInstallation.github_installation_id == installation_id
                        )
                        existing = session.execute(stmt).scalar_one_or_none()
                        
                        if not existing:
                            # Create new installation record with all details
                            installation_record = GitHubInstallation(
                                organization_id=org.id,
                                github_installation_id=installation_id,
                                account_name=account_login,
                                account_type=account_type,
                                account_avatar_url=account_avatar_url,
                                permissions=permissions,
                            )
                            session.add(installation_record)
                            
                            # Update organization with installation ID
                            org.github_installation_id = installation_id
                            
                            # Store repositories
                            from model.tables import Repository
                            for repo in repositories:
                                repo_id = repo.get("id")
                                repo_name = repo.get("name")
                                repo_full_name = repo.get("full_name")
                                repo_private = repo.get("private", False)
                                repo_default_branch = repo.get("default_branch", "main")
                                
                                # Check if repository already exists
                                stmt = select(Repository).where(
                                    Repository.organization_id == org.id,
                                    Repository.github_repo_id == repo_id
                                )
                                existing_repo = session.execute(stmt).scalar_one_or_none()
                                
                                if not existing_repo:
                                    owner = repo_full_name.split("/")[0] if "/" in repo_full_name else account_login
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
                            logger.info(f"GitHub App installation stored for org: {org.name} with {len(repositories)} repositories")
                        else:
                            logger.info(f"GitHub App installation already exists: {installation_id}")
                    else:
                        logger.warning(f"No organization found for user: {account_login}")
                else:
                    logger.warning(f"No user found with GitHub login: {account_login}")
            
            return {
                "status": "received",
                "action": action,
                "installation_id": installation_id,
            }
        
        elif action == "deleted":
            # Installation deleted - remove from database
            with session_scope() as session:
                stmt = select(GitHubInstallation).where(
                    GitHubInstallation.github_installation_id == installation_id
                )
                installation_record = session.execute(stmt).scalar_one_or_none()
                
                if installation_record:
                    session.delete(installation_record)
                    session.commit()
                    logger.info(f"GitHub App installation deleted: {installation_id}")
                
            return {
                "status": "received",
                "action": action,
                "installation_id": installation_id,
            }
    
    # Handle installation_repositories events
    elif x_github_event == "installation_repositories":
        action = data.get("action")
        installation = data.get("installation", {})
        installation_id = installation.get("id")
        
        logger.info(f"GitHub App repositories event: {action}, installation_id: {installation_id}")
        
        return {
            "status": "received",
            "action": action,
            "installation_id": installation_id,
        }
    
    # Ignore other events
    else:
        logger.info(f"Ignoring GitHub App event: {x_github_event}")
        return {"status": "ignored", "event": x_github_event}
