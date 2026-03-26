"""Load user + owned organization for authenticated routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from model.tables import Organization, User


def require_user_and_owned_org(session: Session, user_id: UUID) -> tuple[User, Organization]:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found. Please authenticate first.",
        )
    org = session.execute(
        select(Organization).where(Organization.owner_user_id == user_id)
    ).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return user, org
