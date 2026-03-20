"""Agent configuration and repository management routes."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Body
from pydantic import BaseModel
from sqlalchemy import select

from db import session_scope
from model.tables import User, Organization, Repository, Agent, RepositoryAgent, Model
from model.enums import AgentType
from logger import get_logger
from services.github.coder_workflow import ensure_greagent_labels_on_repository
from services.github.repository_bootstrap import CODER_MODE_AUTO

logger = get_logger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


class RepositoryConfigUpdate(BaseModel):
    enabled: bool
    mode: str


@router.get("/coder/settings")
async def get_coder_settings():
    """
    Get repositories and their configurations for the coder agent.
    
    Returns all repositories in the user's organization and their agent configurations.
    
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
            raise HTTPException(
                status_code=404,
                detail="Organization not found"
            )
        
        # Get or create coder agent for this organization
        stmt = select(Agent).where(
            Agent.organization_id == org.id,
            Agent.type == AgentType.code
        )
        agent = session.execute(stmt).scalar_one_or_none()
        
        if not agent:
            # Create default coder agent
            agent = Agent(
                organization_id=org.id,
                name="Code Agent",
                type=AgentType.code,
            )
            session.add(agent)
            session.flush()
            logger.info(f"Created coder agent for org: {org.name}")
        
        # Get all repositories for this organization
        stmt = select(Repository).where(Repository.organization_id == org.id)
        repositories = session.execute(stmt).scalars().all()
        
        # Get all repository agent configurations
        stmt = select(RepositoryAgent).where(RepositoryAgent.agent_id == agent.id)
        repo_agents = session.execute(stmt).scalars().all()
        
        # Create a map of repository_id to configuration
        config_map = {
            str(ra.repository_id): {
                "enabled": ra.enabled,
                "mode": ra.config_json.get("mode", CODER_MODE_AUTO)
                if ra.config_json
                else CODER_MODE_AUTO,
            }
            for ra in repo_agents
        }
        
        # Build response
        repositories_data = []
        configurations = []
        
        for repo in repositories:
            repo_id_str = str(repo.id)
            
            repositories_data.append({
                "id": repo.github_repo_id,
                "name": repo.name,
                "fullName": f"{repo.owner}/{repo.name}",
                "private": repo.private,
                "owner": repo.owner,
                "description": None,  # TODO: Store description in webhook
                "language": None,  # TODO: Store language in webhook
                "updatedAt": repo.created_at.isoformat() if repo.created_at else None,
            })
            
            if repo_id_str in config_map:
                configurations.append({
                    "repositoryId": repo.github_repo_id,
                    **config_map[repo_id_str],
                })
            else:
                configurations.append({
                    "repositoryId": repo.github_repo_id,
                    "enabled": True,
                    "mode": CODER_MODE_AUTO,
                })
        
        return {
            "repositories": repositories_data,
            "configurations": configurations,
        }


@router.put("/coder/repositories/{repository_id}")
async def update_repository_config(
    repository_id: int = Path(...),
    config: RepositoryConfigUpdate = Body(...)
):
    """
    Update repository configuration for the coder agent.
    
    Args:
        repository_id: GitHub repository ID
        config: Configuration with enabled status and mode
    
    Returns:
        Updated configuration
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
            raise HTTPException(
                status_code=404,
                detail="Organization not found"
            )
        
        # Get repository
        stmt = select(Repository).where(
            Repository.organization_id == org.id,
            Repository.github_repo_id == repository_id
        )
        repo = session.execute(stmt).scalar_one_or_none()
        
        if not repo:
            raise HTTPException(
                status_code=404,
                detail="Repository not found"
            )
        
        # Get or create coder agent
        stmt = select(Agent).where(
            Agent.organization_id == org.id,
            Agent.type == AgentType.code
        )
        agent = session.execute(stmt).scalar_one_or_none()
        
        if not agent:
            agent = Agent(
                organization_id=org.id,
                name="Code Agent",
                type=AgentType.code,
            )
            session.add(agent)
            session.flush()
        
        # Get or create a default model (for now, use first available or create placeholder)
        stmt = select(Model).limit(1)
        model = session.execute(stmt).scalar_one_or_none()
        
        if not model:
            # Create a placeholder model
            model = Model(
                provider="openai",
                name="gpt-4",
            )
            session.add(model)
            session.flush()
        
        # Get or create repository agent configuration
        stmt = select(RepositoryAgent).where(
            RepositoryAgent.repository_id == repo.id,
            RepositoryAgent.agent_id == agent.id
        )
        repo_agent = session.execute(stmt).scalar_one_or_none()
        
        if repo_agent:
            # Update existing configuration
            repo_agent.enabled = config.enabled
            repo_agent.config_json = {"mode": config.mode}
            logger.info(f"Updated repository agent config for repo: {repo.name}")
        else:
            # Create new configuration
            repo_agent = RepositoryAgent(
                repository_id=repo.id,
                agent_id=agent.id,
                model_id=model.id,
                enabled=config.enabled,
                config_json={"mode": config.mode},
            )
            session.add(repo_agent)
            logger.info(f"Created repository agent config for repo: {repo.name}")
        
        session.commit()

        if config.enabled:
            try:
                ensure_greagent_labels_on_repository(repo.owner, repo.name)
            except Exception:
                logger.exception(
                    "Failed to ensure greagent labels for %s/%s",
                    repo.owner,
                    repo.name,
                )
        
        return {
            "repositoryId": repository_id,
            "enabled": config.enabled,
            "mode": config.mode,
        }
