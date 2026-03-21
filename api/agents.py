"""Agent configuration and repository management routes."""

from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy import String, cast, distinct, func, or_, select
from sqlalchemy.orm import Session

from db import session_scope
from model.tables import (
    User,
    Organization,
    Repository,
    Agent,
    RepositoryAgent,
    Model,
    CoderWorkflowUsage,
)
from model.enums import AgentType
from logger import get_logger
from services.github.coder_workflow import ensure_greagent_labels_on_repository
from services.github.repository_bootstrap import CODER_MODE_AUTO

logger = get_logger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


def _get_current_user_org(session: Session) -> tuple[User, Organization]:
    """Resolve the default user and their organization (same pattern as other agent routes)."""
    stmt = select(User).order_by(User.created_at.desc()).limit(1)
    user = session.execute(stmt).scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found. Please authenticate first.",
        )
    stmt = select(Organization).where(Organization.owner_user_id == user.id)
    org = session.execute(stmt).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return user, org


def _get_organization_optional(session: Session) -> Organization | None:
    """Same lookup as ``_get_current_user_org`` but returns None instead of 404."""
    stmt = select(User).order_by(User.created_at.desc()).limit(1)
    user = session.execute(stmt).scalar_one_or_none()
    if not user:
        return None
    stmt = select(Organization).where(Organization.owner_user_id == user.id)
    return session.execute(stmt).scalar_one_or_none()


def _empty_coder_usage_response() -> dict:
    """Payload when no user/org exists yet (e.g. before OAuth) — avoids 404 on the UI."""
    return {
        "summary": {
            "runCount": 0,
            "totalInputTokens": 0,
            "totalOutputTokens": 0,
            "totalTokens": 0,
            "totalCost": "0",
        },
        "repositories": [],
    }


def _org_coder_usage_filter(org_id: UUID, repo_full_names: list[str]):
    """
    Usage rows for this org: recorded with organization_id, or matching a known repo
    full name (covers older rows before repository_id/org_id backfill).
    """
    org_match = CoderWorkflowUsage.organization_id == org_id
    if not repo_full_names:
        return org_match
    return or_(org_match, CoderWorkflowUsage.github_full_name.in_(repo_full_names))


def _fmt_decimal_cost(value: Decimal | None) -> str:
    if value is None:
        return "0"
    return format(value, "f")


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
    with session_scope() as session:
        _, org = _get_current_user_org(session)

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
    with session_scope() as session:
        _, org = _get_current_user_org(session)

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


@router.get("/coder/usage")
async def get_coder_usage(
    repo_limit: int = Query(50, ge=1, le=200, description="Max repositories in response"),
    issue_limit: int = Query(
        100,
        ge=1,
        le=500,
        description="Max issue aggregates fetched (split across repos; nested under each)",
    ),
):
    """
    Aggregated GitHub coder workflow token usage for the current organization.

    Each repository entry includes an ``issues`` array (per-issue token totals),
    sorted by ``lastRunAt`` descending within that repo.
    """
    with session_scope() as session:
        org = _get_organization_optional(session)
        if org is None:
            return _empty_coder_usage_response()

        repos = session.execute(
            select(Repository).where(Repository.organization_id == org.id)
        ).scalars().all()
        full_names = [f"{r.owner}/{r.name}" for r in repos]
        filt = _org_coder_usage_filter(org.id, full_names)

        summary_row = session.execute(
            select(
                func.count(CoderWorkflowUsage.id),
                func.coalesce(func.sum(CoderWorkflowUsage.input_tokens), 0),
                func.coalesce(func.sum(CoderWorkflowUsage.output_tokens), 0),
                func.coalesce(func.sum(CoderWorkflowUsage.total_tokens), 0),
                func.coalesce(func.sum(CoderWorkflowUsage.cost), Decimal("0")),
            ).where(filt)
        ).one()

        run_count, sum_in, sum_out, sum_total, sum_cost = summary_row

        by_repo_stmt = (
            select(
                CoderWorkflowUsage.github_full_name,
                # PostgreSQL has no max(uuid) in many versions; aggregate as text.
                func.max(cast(CoderWorkflowUsage.repository_id, String)).label(
                    "repository_id"
                ),
                func.count(distinct(CoderWorkflowUsage.issue_number)).label(
                    "distinct_issues"
                ),
                func.count(CoderWorkflowUsage.id).label("runs"),
                func.coalesce(func.sum(CoderWorkflowUsage.input_tokens), 0).label(
                    "input_tokens"
                ),
                func.coalesce(func.sum(CoderWorkflowUsage.output_tokens), 0).label(
                    "output_tokens"
                ),
                func.coalesce(func.sum(CoderWorkflowUsage.total_tokens), 0).label(
                    "total_tokens"
                ),
                func.coalesce(func.sum(CoderWorkflowUsage.cost), Decimal("0")).label(
                    "cost"
                ),
            )
            .where(filt)
            .group_by(CoderWorkflowUsage.github_full_name)
            .order_by(func.coalesce(func.sum(CoderWorkflowUsage.total_tokens), 0).desc())
            .limit(repo_limit)
        )
        by_repo_rows = session.execute(by_repo_stmt).all()

        by_issue_stmt = (
            select(
                CoderWorkflowUsage.github_full_name,
                CoderWorkflowUsage.issue_number,
                func.count(CoderWorkflowUsage.id).label("runs"),
                func.coalesce(func.sum(CoderWorkflowUsage.input_tokens), 0).label(
                    "input_tokens"
                ),
                func.coalesce(func.sum(CoderWorkflowUsage.output_tokens), 0).label(
                    "output_tokens"
                ),
                func.coalesce(func.sum(CoderWorkflowUsage.total_tokens), 0).label(
                    "total_tokens"
                ),
                func.coalesce(func.sum(CoderWorkflowUsage.cost), Decimal("0")).label(
                    "cost"
                ),
                func.max(CoderWorkflowUsage.created_at).label("last_run_at"),
            )
            .where(filt)
            .group_by(
                CoderWorkflowUsage.github_full_name,
                CoderWorkflowUsage.issue_number,
            )
            .order_by(func.max(CoderWorkflowUsage.created_at).desc())
            .limit(issue_limit)
        )
        by_issue_rows = session.execute(by_issue_stmt).all()

        issues_by_full_name: dict[str, list[dict]] = defaultdict(list)
        for row in by_issue_rows:
            last_at = (
                row.last_run_at.isoformat() if row.last_run_at else None
            )
            issues_by_full_name[row.github_full_name].append(
                {
                    "issueNumber": int(row.issue_number),
                    "runCount": int(row.runs or 0),
                    "totalInputTokens": int(row.input_tokens or 0),
                    "totalOutputTokens": int(row.output_tokens or 0),
                    "totalTokens": int(row.total_tokens or 0),
                    "totalCost": _fmt_decimal_cost(row.cost),
                    "lastRunAt": last_at,
                }
            )

        for fn in issues_by_full_name:
            issues_by_full_name[fn].sort(
                key=lambda x: x["lastRunAt"] or "",
                reverse=True,
            )

        repositories_out = []
        for row in by_repo_rows:
            fn = row.github_full_name
            repositories_out.append(
                {
                    "githubFullName": fn,
                    "repositoryId": str(row.repository_id)
                    if row.repository_id is not None
                    else None,
                    "distinctIssueCount": int(row.distinct_issues or 0),
                    "runCount": int(row.runs or 0),
                    "totalInputTokens": int(row.input_tokens or 0),
                    "totalOutputTokens": int(row.output_tokens or 0),
                    "totalTokens": int(row.total_tokens or 0),
                    "totalCost": _fmt_decimal_cost(row.cost),
                    "issues": issues_by_full_name.get(fn, []),
                }
            )

        return {
            "summary": {
                "runCount": int(run_count or 0),
                "totalInputTokens": int(sum_in or 0),
                "totalOutputTokens": int(sum_out or 0),
                "totalTokens": int(sum_total or 0),
                "totalCost": _fmt_decimal_cost(sum_cost),
            },
            "repositories": repositories_out,
        }
