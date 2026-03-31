"""Dashboard overview for the authenticated user's organization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from api.deps import get_current_user_id
from api.user_org import require_user_and_owned_org
from db import session_scope
from model.tables import (
    Agent,
    AgentWorkflowUsage,
    OrganizationMember,
    RepositoryAgent,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_RECENT_ACTIVITY_LIMIT = 10


@router.get("")
def get_dashboard(user_id: UUID = Depends(get_current_user_id)):
    """
    Summary stats and recent workflow runs for the user's owned organization.

    - **activeAgentsCount**: Distinct agent types (coder / reviewer) with at least one
      enabled repository binding.
    - **teamMemberCount**: Rows in ``organization_members`` for the org.
    - **activityLast24Hours**: Count of ``agent_workflow_usage`` rows in the last 24 hours.
    - **recentActivity**: Latest usage rows (newest first), capped at 10.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    with session_scope() as session:
        _, org = require_user_and_owned_org(session, user_id)
        org_id = org.id

        active_agents = session.execute(
            select(func.count(func.distinct(RepositoryAgent.agent_id)))
            .select_from(RepositoryAgent)
            .join(Agent, Agent.id == RepositoryAgent.agent_id)
            .where(
                Agent.organization_id == org_id,
                RepositoryAgent.enabled.is_(True),
            )
        ).scalar_one()
        active_agents_count = int(active_agents or 0)

        member_count = session.execute(
            select(func.count(OrganizationMember.id)).where(
                OrganizationMember.organization_id == org_id
            )
        ).scalar_one()
        team_member_count = int(member_count or 0)

        activity_24h = session.execute(
            select(func.count(AgentWorkflowUsage.id)).where(
                AgentWorkflowUsage.organization_id == org_id,
                AgentWorkflowUsage.created_at >= cutoff,
            )
        ).scalar_one()
        activity_last_24h = int(activity_24h or 0)

        recent_rows = session.execute(
            select(AgentWorkflowUsage)
            .where(AgentWorkflowUsage.organization_id == org_id)
            .order_by(AgentWorkflowUsage.created_at.desc())
            .limit(_RECENT_ACTIVITY_LIMIT)
        ).scalars().all()

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
        "teamMemberCount": team_member_count,
        "activityLast24Hours": activity_last_24h,
        "recentActivity": recent_activity,
    }
