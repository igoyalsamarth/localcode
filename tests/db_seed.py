"""Shared ORM seeds for tests (organizations + membership)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from model.tables import Organization, User


def seed_user(session: Session, *, email: str = "u@e.com", username: str = "u") -> User:
    u = User(email=email, username=username, auth_provider="github")
    session.add(u)
    session.flush()
    return u


def seed_workspace(
    session: Session,
    user: User,
    *,
    name: str = "O",
    is_personal: bool = False,
) -> Organization:
    org = Organization(
        name=name,
        is_personal=is_personal,
        created_by_user_id=user.id,
        owner_user_id=user.id,
    )
    session.add(org)
    session.flush()
    return org
