"""Agent configuration and repository management routes."""

from collections import defaultdict
from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy import String, cast, distinct, func, select

from api.deps import get_current_org_id, get_current_user_id
from api.user_org import require_org_membership, require_workspace_role
from db import session_scope
from logger import get_logger
from model.enums import AgentType, GitHubWorkflowKind, MemberRole
from model.tables import Agent, AgentWorkflowUsage, Repository, RepositoryAgent
from services.github.coder_workflow import ensure_greagent_labels_on_repository
from services.github.repository_bootstrap import get_or_create_default_model
from services.github.review_workflow import ensure_greagent_review_labels_on_repository
from services.github.trigger_modes import TRIGGER_MODE_AUTO

logger = get_logger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


def _fmt_decimal_cost(value: Decimal | None) -> str:
    if value is None:
        return "0"
    return format(value, "f")


class RepositoryConfigUpdate(BaseModel):
    enabled: bool
    mode: str


_AGENT_DISPLAY_NAMES: dict[AgentType, str] = {
    AgentType.code: "Code Agent",
    AgentType.review: "Review Agent",
}


def _ensure_org_agent(session, org, agent_type: AgentType) -> Agent:
    stmt = select(Agent).where(
        Agent.organization_id == org.id,
        Agent.type == agent_type,
    )
    agent = session.execute(stmt).scalar_one_or_none()
    if not agent:
        agent = Agent(
            organization_id=org.id,
            name=_AGENT_DISPLAY_NAMES[agent_type],
            type=agent_type,
        )
        session.add(agent)
        session.flush()
        logger.info(
            "Created %s agent for org: %s",
            agent_type.value,
            org.name,
        )
    return agent


def _agent_settings_payload(session, org, agent: Agent) -> dict:
    stmt = select(Repository).where(Repository.organization_id == org.id)
    repositories = session.execute(stmt).scalars().all()

    stmt = select(RepositoryAgent).where(RepositoryAgent.agent_id == agent.id)
    repo_agents = session.execute(stmt).scalars().all()

    config_map = {
        str(ra.repository_id): {
            "enabled": ra.enabled,
            "mode": (
                ra.config_json.get("mode", TRIGGER_MODE_AUTO)
                if ra.config_json
                else TRIGGER_MODE_AUTO
            ),
        }
        for ra in repo_agents
    }

    repositories_data = []
    configurations = []

    for repo in repositories:
        repo_id_str = str(repo.id)

        repositories_data.append(
            {
                "id": repo.github_repo_id,
                "name": repo.name,
                "fullName": f"{repo.owner}/{repo.name}",
                "private": repo.private,
                "owner": repo.owner,
                "description": None,
                "language": None,
                "updatedAt": repo.created_at.isoformat() if repo.created_at else None,
            }
        )

        if repo_id_str in config_map:
            configurations.append(
                {
                    "repositoryId": repo.github_repo_id,
                    **config_map[repo_id_str],
                }
            )
        else:
            configurations.append(
                {
                    "repositoryId": repo.github_repo_id,
                    "enabled": True,
                    "mode": TRIGGER_MODE_AUTO,
                }
            )

    return {
        "repositories": repositories_data,
        "configurations": configurations,
    }


def _update_repository_agent_config(
    session,
    org,
    repository_id: int,
    config: RepositoryConfigUpdate,
    agent_type: AgentType,
    *,
    on_enabled_labels: Callable[[str, str], None] | None,
) -> dict:
    stmt = select(Repository).where(
        Repository.organization_id == org.id,
        Repository.github_repo_id == repository_id,
    )
    repo = session.execute(stmt).scalar_one_or_none()

    if not repo:
        raise HTTPException(
            status_code=404,
            detail="Repository not found",
        )

    agent = _ensure_org_agent(session, org, agent_type)

    model = get_or_create_default_model(session)

    stmt = select(RepositoryAgent).where(
        RepositoryAgent.repository_id == repo.id,
        RepositoryAgent.agent_id == agent.id,
    )
    repo_agent = session.execute(stmt).scalar_one_or_none()

    if repo_agent:
        repo_agent.enabled = config.enabled
        repo_agent.config_json = {"mode": config.mode}
        logger.info(
            "Updated %s repository agent config for repo: %s",
            agent_type.value,
            repo.name,
        )
    else:
        repo_agent = RepositoryAgent(
            repository_id=repo.id,
            agent_id=agent.id,
            model_id=model.id,
            enabled=config.enabled,
            config_json={"mode": config.mode},
        )
        session.add(repo_agent)
        logger.info(
            "Created %s repository agent config for repo: %s",
            agent_type.value,
            repo.name,
        )

    session.commit()

    if config.enabled and on_enabled_labels is not None:
        try:
            on_enabled_labels(repo.owner, repo.name)
        except Exception:
            logger.exception(
                "Failed to ensure labels for %s agent on %s/%s",
                agent_type.value,
                repo.owner,
                repo.name,
            )

    return {
        "repositoryId": repository_id,
        "enabled": config.enabled,
        "mode": config.mode,
    }


@router.get("/coder/settings")
async def get_coder_settings(
    user_id: UUID = Depends(get_current_user_id),
    org_id: UUID = Depends(get_current_org_id),
):
    """
    Get repositories and their configurations for the coder agent.

    Returns all repositories in the user's organization and their agent configurations.
    """
    with session_scope() as session:
        _, org, _ = require_org_membership(session, user_id, org_id)
        agent = _ensure_org_agent(session, org, AgentType.code)
        return _agent_settings_payload(session, org, agent)


@router.put("/coder/repositories/{repository_id}")
async def update_coder_repository_config(
    repository_id: int = Path(...),
    config: RepositoryConfigUpdate = Body(...),
    user_id: UUID = Depends(get_current_user_id),
    org_id: UUID = Depends(get_current_org_id),
):
    """Update repository configuration for the coder agent."""
    with session_scope() as session:
        _, org, member = require_org_membership(session, user_id, org_id)
        require_workspace_role(member, MemberRole.admin)
        return _update_repository_agent_config(
            session,
            org,
            repository_id,
            config,
            AgentType.code,
            on_enabled_labels=ensure_greagent_labels_on_repository,
        )


@router.get("/reviewer/settings")
async def get_reviewer_settings(
    user_id: UUID = Depends(get_current_user_id),
    org_id: UUID = Depends(get_current_org_id),
):
    """
    Get repositories and their configurations for the reviewer agent.

    Same response shape as ``GET /agents/coder/settings``.
    """
    with session_scope() as session:
        _, org, _ = require_org_membership(session, user_id, org_id)
        agent = _ensure_org_agent(session, org, AgentType.review)
        return _agent_settings_payload(session, org, agent)


@router.put("/reviewer/repositories/{repository_id}")
async def update_reviewer_repository_config(
    repository_id: int = Path(...),
    config: RepositoryConfigUpdate = Body(...),
    user_id: UUID = Depends(get_current_user_id),
    org_id: UUID = Depends(get_current_org_id),
):
    """Update repository configuration for the reviewer agent."""
    with session_scope() as session:
        _, org, member = require_org_membership(session, user_id, org_id)
        require_workspace_role(member, MemberRole.admin)
        return _update_repository_agent_config(
            session,
            org,
            repository_id,
            config,
            AgentType.review,
            on_enabled_labels=ensure_greagent_review_labels_on_repository,
        )


def _workflow_usage_payload(
    *,
    org_id: UUID,
    repo_limit: int,
    item_limit: int,
    workflow: GitHubWorkflowKind | None,
    trigger_user_id: UUID | None = None,
) -> dict:
    filt = AgentWorkflowUsage.organization_id == org_id
    if workflow is not None:
        filt = filt & (AgentWorkflowUsage.workflow == workflow)
    if trigger_user_id is not None:
        filt = filt & (AgentWorkflowUsage.trigger_user_id == trigger_user_id)

    with session_scope() as session:
        summary_row = session.execute(
            select(
                func.count(AgentWorkflowUsage.id),
                func.coalesce(func.sum(AgentWorkflowUsage.input_tokens), 0),
                func.coalesce(func.sum(AgentWorkflowUsage.output_tokens), 0),
                func.coalesce(func.sum(AgentWorkflowUsage.total_tokens), 0),
                func.coalesce(func.sum(AgentWorkflowUsage.cost), Decimal("0")),
            ).where(filt)
        ).one()

        run_count, sum_in, sum_out, sum_total, sum_cost = summary_row

        by_repo_stmt = (
            select(
                AgentWorkflowUsage.github_full_name,
                AgentWorkflowUsage.workflow,
                func.max(cast(AgentWorkflowUsage.repository_id, String)).label(
                    "repository_id"
                ),
                func.count(distinct(AgentWorkflowUsage.github_item_number)).label(
                    "distinct_items"
                ),
                func.count(AgentWorkflowUsage.id).label("runs"),
                func.coalesce(func.sum(AgentWorkflowUsage.input_tokens), 0).label(
                    "input_tokens"
                ),
                func.coalesce(func.sum(AgentWorkflowUsage.output_tokens), 0).label(
                    "output_tokens"
                ),
                func.coalesce(func.sum(AgentWorkflowUsage.total_tokens), 0).label(
                    "total_tokens"
                ),
                func.coalesce(func.sum(AgentWorkflowUsage.cost), Decimal("0")).label(
                    "cost"
                ),
            )
            .where(filt)
            .group_by(
                AgentWorkflowUsage.github_full_name,
                AgentWorkflowUsage.workflow,
            )
            .order_by(
                func.coalesce(func.sum(AgentWorkflowUsage.total_tokens), 0).desc()
            )
            .limit(repo_limit)
        )
        by_repo_rows = session.execute(by_repo_stmt).all()

        by_item_stmt = (
            select(
                AgentWorkflowUsage.github_full_name,
                AgentWorkflowUsage.workflow,
                AgentWorkflowUsage.github_item_number,
                func.count(AgentWorkflowUsage.id).label("runs"),
                func.coalesce(func.sum(AgentWorkflowUsage.input_tokens), 0).label(
                    "input_tokens"
                ),
                func.coalesce(func.sum(AgentWorkflowUsage.output_tokens), 0).label(
                    "output_tokens"
                ),
                func.coalesce(func.sum(AgentWorkflowUsage.total_tokens), 0).label(
                    "total_tokens"
                ),
                func.coalesce(func.sum(AgentWorkflowUsage.cost), Decimal("0")).label(
                    "cost"
                ),
                func.max(AgentWorkflowUsage.created_at).label("last_run_at"),
            )
            .where(filt)
            .group_by(
                AgentWorkflowUsage.github_full_name,
                AgentWorkflowUsage.workflow,
                AgentWorkflowUsage.github_item_number,
            )
            .order_by(func.max(AgentWorkflowUsage.created_at).desc())
            .limit(item_limit)
        )
        by_item_rows = session.execute(by_item_stmt).all()

    items_by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in by_item_rows:
        key = (row.github_full_name, row.workflow.value)
        last_at = row.last_run_at.isoformat() if row.last_run_at else None
        items_by_key[key].append(
            {
                "workflow": row.workflow.value,
                "itemNumber": int(row.github_item_number),
                "runCount": int(row.runs or 0),
                "totalInputTokens": int(row.input_tokens or 0),
                "totalOutputTokens": int(row.output_tokens or 0),
                "totalTokens": int(row.total_tokens or 0),
                "totalCost": _fmt_decimal_cost(row.cost),
                "lastRunAt": last_at,
            }
        )

    for key in items_by_key:
        items_by_key[key].sort(
            key=lambda x: x["lastRunAt"] or "",
            reverse=True,
        )

    repositories_out = []
    for row in by_repo_rows:
        key = (row.github_full_name, row.workflow.value)
        wf = row.workflow.value
        repositories_out.append(
            {
                "githubFullName": row.github_full_name,
                "workflow": wf,
                "repositoryId": (
                    str(row.repository_id) if row.repository_id is not None else None
                ),
                "distinctItemCount": int(row.distinct_items or 0),
                "runCount": int(row.runs or 0),
                "totalInputTokens": int(row.input_tokens or 0),
                "totalOutputTokens": int(row.output_tokens or 0),
                "totalTokens": int(row.total_tokens or 0),
                "totalCost": _fmt_decimal_cost(row.cost),
                "items": items_by_key.get(key, []),
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


@router.get("/usage")
async def get_workflow_usage(
    user_id: UUID = Depends(get_current_user_id),
    org_id: UUID = Depends(get_current_org_id),
    workflow: GitHubWorkflowKind | None = Query(
        None,
        description="Filter by workflow: code (issues) or review (PRs). Omit for all.",
    ),
    repo_limit: int = Query(
        50, ge=1, le=200, description="Max repository/workflow rows"
    ),
    item_limit: int = Query(
        100,
        ge=1,
        le=500,
        description="Max item aggregates (split across repos/workflows)",
    ),
):
    """
    Aggregated token usage for GitHub deep-agent runs, filterable by ``workflow``.

    Each repository entry is scoped to one workflow (``code`` or ``review``). Nested
    ``items`` include the same ``workflow`` plus ``itemNumber`` (issue or PR number).
    """
    with session_scope() as session:
        _, _, member = require_org_membership(session, user_id, org_id)
        uid_filter = user_id if member.role == MemberRole.user else None

    return _workflow_usage_payload(
        org_id=org_id,
        repo_limit=repo_limit,
        item_limit=item_limit,
        workflow=workflow,
        trigger_user_id=uid_filter,
    )
