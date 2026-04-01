"""Dashboard overview for the authenticated organization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from api.deps import get_current_org_id, get_current_user_id
from api.user_org import require_org_membership
from db import session_scope
from model.tables import Agent, AgentWorkflowUsage, RepositoryAgent

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_RECENT_ACTIVITY_LIMIT = 10


@router.get("")
def get_dashboard(
    user_id: UUID = Depends(get_current_user_id),
    org_id: UUID = Depends(get_current_org_id),
):
    """
    Summary stats and recent workflow runs for the organization (single owner account).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    with session_scope() as session:
        _, org = require_org_membership(session, user_id, org_id)

        active_agents = session.execute(
            select(func.count(func.distinct(RepositoryAgent.agent_id)))
            .select_from(RepositoryAgent)
            .join(Agent, Agent.id == RepositoryAgent.agent_id)
            .where(
                Agent.organization_id == org.id,
                RepositoryAgent.enabled.is_(True),
            )
        ).scalar_one()
        active_agents_count = int(active_agents or 0)

        activity_24h = session.execute(
            select(func.count(AgentWorkflowUsage.id)).where(
                AgentWorkflowUsage.organization_id == org.id,
                AgentWorkflowUsage.created_at >= cutoff,
            )
        ).scalar_one()
        activity_last_24h = int(activity_24h or 0)

        recent_rows = list(
            session.execute(
                select(AgentWorkflowUsage)
                .where(AgentWorkflowUsage.organization_id == org.id)
                .order_by(AgentWorkflowUsage.created_at.desc())
                .limit(_RECENT_ACTIVITY_LIMIT)
            ).scalars().all()
        )

    recent_activity = []
    for row in recent_rows:
        ts = row.created_at.isoformat() if row.created_at else None
        recent_activity.append(
            {
                "workflow": row.workflow.value,
                "githubFullName": row.github_full_name,
                "itemNumber": int(row.github_item_number),
                "createdAt": ts,
            }
        )

    return {
        "activeAgentsCount": active_agents_count,
        "activityLast24Hours": activity_last_24h,
        "recentActivity": recent_activity,
    }
