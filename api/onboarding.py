"""User onboarding endpoint."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from db import session_scope
from model.tables import User, Organization
from model.schemas import OnboardingRequest
from logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.post("")
async def complete_onboarding(data: OnboardingRequest):
    """
    Complete user onboarding by updating profile information.
    
    Args:
        data: Onboarding data including organization name, username, full name, and bio
    
    Returns:
        Updated user and organization information
    """
    if not data.username or len(data.username) < 3:
        raise HTTPException(
            status_code=400,
            detail="Username must be at least 3 characters"
        )
    
    if not data.organization or len(data.organization) < 2:
        raise HTTPException(
            status_code=400,
            detail="Organization name must be at least 2 characters"
        )
    
    if data.bio and len(data.bio) > 160:
        raise HTTPException(
            status_code=400,
            detail="Bio must be 160 characters or less"
        )
    
    # TODO: Get user_id from JWT token or session
    # For now, this is a placeholder - you'll need to implement authentication middleware
    # that extracts the user_id from the request
    
    # This is temporary - in production, get user_id from authenticated session
    with session_scope() as session:
        # For demo purposes, find the most recently created user
        # In production, get user_id from JWT/session
        stmt = select(User).order_by(User.created_at.desc()).limit(1)
        user = session.execute(stmt).scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found. Please authenticate first."
            )
        
        # Check if username is already taken
        if data.username != user.username:
            stmt = select(User).where(User.username == data.username)
            existing_user = session.execute(stmt).scalar_one_or_none()
            if existing_user:
                raise HTTPException(
                    status_code=400,
                    detail="Username already taken"
                )
        
        # Update user profile
        user.username = data.username
        user.name = data.fullName
        user.bio = data.bio
        user.onboarded = True
        
        # Update organization name
        stmt = select(Organization).where(Organization.owner_user_id == user.id)
        organization = session.execute(stmt).scalar_one_or_none()
        
        if organization:
            organization.name = data.organization
        else:
            raise HTTPException(
                status_code=404,
                detail="Organization not found"
            )
        
        session.commit()
        
        logger.info(f"User onboarding completed: {user.username}, Org: {organization.name}")
        
        return {
            "status": "success",
            "user": {
                "id": str(user.id),
                "username": user.username,
                "name": user.name,
                "bio": user.bio,
                "email": user.email,
                "github_login": user.github_login,
                "avatar_url": user.avatar_url,
                "onboarded": user.onboarded,
            },
            "organization": {
                "id": str(organization.id),
                "name": organization.name,
            },
        }
