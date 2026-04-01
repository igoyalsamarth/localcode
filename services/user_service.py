"""User and workspace (organization) management."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from model.enums import MemberRole
from model.tables import Organization, OrganizationMember, User
from logger import get_logger
from services.wallet import signup_promotional_credit_defaults

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
    Return the user's personal workspace, creating it on first sign-in.

    Personal workspaces receive signup promotional credit. Name: ``{login}'s workspace``.
    """
    stmt = (
        select(Organization)
        .join(OrganizationMember)
        .where(
            OrganizationMember.user_id == user.id,
            Organization.is_personal.is_(True),
        )
        .limit(1)
    )
    org = session.execute(stmt).scalar_one_or_none()
    if org:
        logger.info("Found personal workspace: %s", org.name)
        return org

    login = user.github_login or user.username
    display = f"{login}'s workspace"
    logger.info("Creating personal workspace: %s", display)

    promo_usd, promo_expires = signup_promotional_credit_defaults()
    org = Organization(
        name=display,
        is_personal=True,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        promotional_balance_usd=promo_usd,
        promotional_balance_expires_at=promo_expires,
    )
    session.add(org)
    session.flush()

    session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=MemberRole.creator,
        )
    )
    user.onboarded = True
    session.flush()
    logger.info("Personal workspace created for %s", login)
    return org


def create_team_workspace(session: Session, creator: User, name: str) -> Organization:
    """
    Create an additional workspace (no signup promo). Creator becomes ``MemberRole.creator``.

    ``owner_user_id`` is the creator for billing ownership.
    """
    org = Organization(
        name=name.strip(),
        is_personal=False,
        created_by_user_id=creator.id,
        owner_user_id=creator.id,
    )
    session.add(org)
    session.flush()
    session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=creator.id,
            role=MemberRole.creator,
        )
    )
    session.flush()
    logger.info("Team workspace %s created by %s", org.name, creator.username)
    return org


def get_user_by_github_id(session: Session, github_user_id: int) -> User | None:
    stmt = select(User).where(User.github_user_id == github_user_id)
    return session.execute(stmt).scalar_one_or_none()


def get_user_by_email(session: Session, email: str) -> User | None:
    stmt = select(User).where(User.email == email)
    return session.execute(stmt).scalar_one_or_none()


def get_user_by_username(session: Session, username: str) -> User | None:
    stmt = select(User).where(User.username == username)
    return session.execute(stmt).scalar_one_or_none()


def get_personal_workspace_for_user(session: Session, user_id: UUID) -> Organization | None:
    """GitHub App installs attach to the user's personal workspace."""
    stmt = (
        select(Organization)
        .join(OrganizationMember)
        .where(
            OrganizationMember.user_id == user_id,
            Organization.is_personal.is_(True),
        )
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()
