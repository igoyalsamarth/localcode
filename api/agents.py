"""Agent configuration and repository management routes."""

from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy import String, cast, distinct, func, or_, select

from api.deps import get_current_user_id
from api.user_org import require_user_and_owned_org
from db import session_scope
from logger import get_logger
from model.enums import AgentType, GitHubWorkflowKind
from model.tables import Agent, AgentWorkflowUsage, Model, Repository, RepositoryAgent
from services.github.coder_workflow import ensure_greagent_labels_on_repository
from services.github.trigger_modes import TRIGGER_MODE_AUTO

logger = get_logger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


def _org_workflow_usage_filter(org_id: UUID, repo_full_names: list[str]):
    """
    Usage rows for this org: recorded with organization_id, or matching a known repo
    full name (covers older rows before repository_id/org_id backfill).
    """
    org_match = AgentWorkflowUsage.organization_id == org_id
    if not repo_full_names:
        return org_match
    return or_(org_match, AgentWorkflowUsage.github_full_name.in_(repo_full_names))


def _fmt_decimal_cost(value: Decimal | None) -> str:
    if value is None:
        return "0"
    return format(value, "f")


class RepositoryConfigUpdate(BaseModel):
    enabled: bool
    mode: str


@router.get("/coder/settings")
async def get_coder_settings(user_id: UUID = Depends(get_current_user_id)):
    """
    Get repositories and their configurations for the coder agent.

    Returns all repositories in the user's organization and their agent configurations.
    """
    with session_scope() as session:
        _, org = require_user_and_owned_org(session, user_id)

        stmt = select(Agent).where(
            Agent.organization_id == org.id,
            Agent.type == AgentType.code,
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
            logger.info(f"Created coder agent for org: {org.name}")

        stmt = select(Repository).where(Repository.organization_id == org.id)
        repositories = session.execute(stmt).scalars().all()

        stmt = select(RepositoryAgent).where(RepositoryAgent.agent_id == agent.id)
        repo_agents = session.execute(stmt).scalars().all()

        config_map = {
            str(ra.repository_id): {
                "enabled": ra.enabled,
                "mode": ra.config_json.get("mode", TRIGGER_MODE_AUTO)
                if ra.config_json
                else TRIGGER_MODE_AUTO,
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


@router.put("/coder/repositories/{repository_id}")
async def update_repository_config(
    repository_id: int = Path(...),
    config: RepositoryConfigUpdate = Body(...),
    user_id: UUID = Depends(get_current_user_id),
):
    """
    Update repository configuration for the coder agent.
    """
    with session_scope() as session:
        _, org = require_user_and_owned_org(session, user_id)

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

        stmt = select(Agent).where(
            Agent.organization_id == org.id,
            Agent.type == AgentType.code,
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

        stmt = select(Model).limit(1)
        model = session.execute(stmt).scalar_one_or_none()

        if not model:
            model = Model(
                provider="openai",
                name="gpt-4",
            )
            session.add(model)
            session.flush()

        stmt = select(RepositoryAgent).where(
            RepositoryAgent.repository_id == repo.id,
            RepositoryAgent.agent_id == agent.id,
        )
        repo_agent = session.execute(stmt).scalar_one_or_none()

        if repo_agent:
            repo_agent.enabled = config.enabled
            repo_agent.config_json = {"mode": config.mode}
            logger.info(f"Updated repository agent config for repo: {repo.name}")
        else:
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


def _workflow_usage_payload(
    *,
    org_id: UUID,
    full_names: list[str],
    repo_limit: int,
    item_limit: int,
    workflow: GitHubWorkflowKind | None,
) -> dict:
    filt = _org_workflow_usage_filter(org_id, full_names)
    if workflow is not None:
        filt = filt & (AgentWorkflowUsage.workflow == workflow)

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
                "repositoryId": str(row.repository_id)
                if row.repository_id is not None
                else None,
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
    workflow: GitHubWorkflowKind | None = Query(
        None,
        description="Filter by workflow: code (issues) or review (PRs). Omit for all.",
    ),
    repo_limit: int = Query(50, ge=1, le=200, description="Max repository/workflow rows"),
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
        _, org = require_user_and_owned_org(session, user_id)
        repos = session.execute(
            select(Repository).where(Repository.organization_id == org.id)
        ).scalars().all()
        full_names = [f"{r.owner}/{r.name}" for r in repos]

    return _workflow_usage_payload(
        org_id=org.id,
        full_names=full_names,
        repo_limit=repo_limit,
        item_limit=item_limit,
        workflow=workflow,
    )


@router.get("/coder/usage")
async def get_coder_usage_legacy(
    user_id: UUID = Depends(get_current_user_id),
    repo_limit: int = Query(50, ge=1, le=200),
    issue_limit: int = Query(100, ge=1, le=500),
):
    """
    Same data as ``GET /agents/usage?workflow=code`` with legacy response shape (``issues``).
    """
    with session_scope() as session:
        _, org = require_user_and_owned_org(session, user_id)
        repos = session.execute(
            select(Repository).where(Repository.organization_id == org.id)
        ).scalars().all()
        full_names = [f"{r.owner}/{r.name}" for r in repos]

    payload = _workflow_usage_payload(
        org_id=org.id,
        full_names=full_names,
        repo_limit=repo_limit,
        item_limit=issue_limit,
        workflow=GitHubWorkflowKind.code,
    )
    for repo in payload["repositories"]:
        repo["distinctIssueCount"] = repo.pop("distinctItemCount")
        repo["issues"] = repo.pop("items")
        for item in repo["issues"]:
            item["issueNumber"] = item.pop("itemNumber")
            item.pop("workflow", None)
    return payload
