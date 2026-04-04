"""User and organization management."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from constants import SIGNUP_PROMO_WALLET_USD
from model.tables import Organization, User
from logger import get_logger

logger = get_logger(__name__)


def create_or_update_user(
    session: Session,
    email: str,
    name: str | None,
    github_user_id: int,
    github_login: str,
    avatar_url: str | None,
) -> User:
    """Create or update a user from GitHub OAuth; ``username`` is always the GitHub login."""
    stmt = select(User).where(User.github_user_id == github_user_id)
    user = session.execute(stmt).scalar_one_or_none()

    if user:
        logger.info("Updating existing user: %s", github_login)
        user.email = email
        user.name = name
        user.github_login = github_login
        user.username = github_login
        user.avatar_url = avatar_url
    else:
        logger.info("Creating new user: %s", github_login)
        user = User(
            email=email,
            name=name,
            username=github_login,
            github_user_id=github_user_id,
            github_login=github_login,
            avatar_url=avatar_url,
            auth_provider="github",
        )
        session.add(user)

    session.flush()
    return user


def get_or_create_personal_workspace(session: Session, user: User) -> Organization:
    """
    Return the user's personal organization, creating it on first sign-in.

    Initial wallet credit applies (``SIGNUP_PROMO_WALLET_USD``). Name: ``{login}'s workspace``.
    """
    stmt = (
        select(Organization)
        .where(
            Organization.owner_user_id == user.id,
            Organization.is_personal.is_(True),
        )
        .limit(1)
    )
    org = session.execute(stmt).scalar_one_or_none()
    if org:
        logger.info("Found personal organization: %s", org.name)
        return org

    display = f"{user.username}'s workspace"
    logger.info("Creating personal organization: %s for %s", display, user.username)

    org = Organization(
        name=display,
        is_personal=True,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        wallet_balance_usd=SIGNUP_PROMO_WALLET_USD,
    )
    session.add(org)
    session.flush()
    logger.info("Personal organization created for %s", user.username)
    return org


def get_organization_for_user(session: Session, user_id: UUID) -> Organization | None:
    """Return the organization owned by this user (one per account)."""
    stmt = select(Organization).where(Organization.owner_user_id == user_id).limit(1)
    return session.execute(stmt).scalar_one_or_none()


def get_user_by_github_id(session: Session, github_user_id: int) -> User | None:
    stmt = select(User).where(User.github_user_id == github_user_id)
    return session.execute(stmt).scalar_one_or_none()


def get_user_by_email(session: Session, email: str) -> User | None:
    stmt = select(User).where(User.email == email)
    return session.execute(stmt).scalar_one_or_none()
