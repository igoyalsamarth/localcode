"""Resolve authenticated user and organization from JWT (single owner per org)."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from model.tables import Organization, User


def require_org_membership(
    session: Session, user_id: UUID, org_id: UUID
) -> tuple[User, Organization]:
    """
    Load user and organization; require ``org.owner_user_id == user_id``.

    Raises 404 if user or org is missing, 403 if the user does not own the org.
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found. Please authenticate first.",
        )
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if org.owner_user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this organization",
        )
    return user, org
