"""Resolve authenticated user and organization (workspace) from JWT + membership."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from model.enums import MemberRole
from model.tables import Organization, OrganizationMember, User


def require_org_membership(
    session: Session, user_id: UUID, org_id: UUID
) -> tuple[User, Organization, OrganizationMember]:
    """
    Load user and organization; require an ``OrganizationMember`` row for ``org_id``.

    Raises 404 if user or org is missing, 403 if the user is not a member.
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found. Please authenticate first.",
        )
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Workspace not found")

    member = session.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    if not member:
        raise HTTPException(
            status_code=403,
            detail="You are not a member of this workspace",
        )
    return user, org, member


def role_at_least(role: MemberRole, minimum: MemberRole) -> bool:
    """True if ``role`` has at least the privileges of ``minimum``."""
    order = {MemberRole.user: 0, MemberRole.admin: 1, MemberRole.creator: 2}
    return order.get(role, 0) >= order[minimum]


def require_workspace_role(
    member: OrganizationMember, minimum: MemberRole
) -> None:
    if not role_at_least(member.role, minimum):
        raise HTTPException(
            status_code=403,
            detail="Insufficient permissions for this workspace",
        )
