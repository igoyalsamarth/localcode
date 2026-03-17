"""User and organization management service."""

from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import select

from model.tables import User, Organization, OrganizationMember, Subscription
from model.enums import MemberRole, SubscriptionStatus, BillingCycle
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
    """
    Create a new user or update existing user with GitHub data.
    
    Args:
        session: Database session
        email: User email
        name: User full name
        github_user_id: GitHub user ID
        github_login: GitHub username
        avatar_url: GitHub avatar URL
    
    Returns:
        User object (new or updated)
    """
    stmt = select(User).where(User.github_user_id == github_user_id)
    user = session.execute(stmt).scalar_one_or_none()
    
    if user:
        logger.info(f"Updating existing user: {github_login}")
        user.email = email
        user.name = name
        user.github_login = github_login
        user.avatar_url = avatar_url
    else:
        logger.info(f"Creating new user: {github_login}")
        user = User(
            email=email,
            name=name,
            github_user_id=github_user_id,
            github_login=github_login,
            avatar_url=avatar_url,
            auth_provider="github",
        )
        session.add(user)
    
    session.flush()
    return user


def get_or_create_organization(
    session: Session,
    user: User,
    org_name: str | None = None,
) -> Organization:
    """
    Get user's personal organization or create one if it doesn't exist.
    
    Args:
        session: Database session
        user: User object
        org_name: Optional organization name (defaults to user's GitHub login)
    
    Returns:
        Organization object
    """
    stmt = select(Organization).where(Organization.owner_user_id == user.id)
    org = session.execute(stmt).scalar_one_or_none()
    
    if org:
        logger.info(f"Found existing organization: {org.name}")
        return org
    
    org_name = org_name or user.github_login or "Personal Organization"
    logger.info(f"Creating new organization: {org_name}")
    
    org = Organization(
        name=org_name,
        owner_user_id=user.id,
    )
    session.add(org)
    session.flush()
    
    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=MemberRole.owner,
    )
    session.add(member)
    
    subscription = Subscription(
        organization_id=org.id,
        status=SubscriptionStatus.active,
        billing_cycle=BillingCycle.monthly,
    )
    session.add(subscription)
    
    session.flush()
    logger.info(f"Created organization with subscription for user: {user.github_login}")
    
    return org


def get_user_by_github_id(session: Session, github_user_id: int) -> User | None:
    """Get user by GitHub user ID."""
    stmt = select(User).where(User.github_user_id == github_user_id)
    return session.execute(stmt).scalar_one_or_none()


def get_user_by_email(session: Session, email: str) -> User | None:
    """Get user by email."""
    stmt = select(User).where(User.email == email)
    return session.execute(stmt).scalar_one_or_none()
