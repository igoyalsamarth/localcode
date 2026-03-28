"""Tests for user service."""

import pytest
from uuid import uuid4

from services.user_service import (
    create_or_update_user,
    get_or_create_organization,
    get_user_by_github_id,
    get_user_by_email,
)
from model.tables import User, Organization, OrganizationMember
from model.enums import MemberRole


@pytest.mark.unit
class TestUserService:
    """Test user service functions."""

    def test_create_or_update_user_new(self, db_session):
        """Test creating a new user."""
        user = create_or_update_user(
            db_session,
            email="test@example.com",
            name="Test User",
            github_user_id=12345,
            github_login="testuser",
            avatar_url="https://github.com/avatar.png",
        )
        
        assert user is not None
        assert user.email == "test@example.com"
        assert user.name == "Test User"
        assert user.github_user_id == 12345
        assert user.github_login == "testuser"
        assert user.avatar_url == "https://github.com/avatar.png"
        assert user.auth_provider == "github"

    def test_create_or_update_user_existing(self, db_session):
        """Test updating an existing user."""
        user1 = create_or_update_user(
            db_session,
            email="test@example.com",
            name="Test User",
            github_user_id=12345,
            github_login="testuser",
            avatar_url="https://github.com/avatar.png",
        )
        db_session.commit()
        
        user2 = create_or_update_user(
            db_session,
            email="updated@example.com",
            name="Updated User",
            github_user_id=12345,
            github_login="updateduser",
            avatar_url="https://github.com/new-avatar.png",
        )
        
        assert user2.id == user1.id
        assert user2.email == "updated@example.com"
        assert user2.name == "Updated User"
        assert user2.github_login == "updateduser"

    def test_get_or_create_organization_new(self, db_session):
        """Test creating a new organization."""
        user = create_or_update_user(
            db_session,
            email="test@example.com",
            name="Test User",
            github_user_id=12345,
            github_login="testuser",
            avatar_url=None,
        )
        db_session.commit()
        
        org = get_or_create_organization(db_session, user, "Test Org")
        
        assert org is not None
        assert org.name == "Test Org"
        assert org.owner_user_id == user.id
        
        member = db_session.query(OrganizationMember).filter_by(
            organization_id=org.id,
            user_id=user.id,
        ).first()
        assert member is not None
        assert member.role == MemberRole.owner

    def test_get_or_create_organization_existing(self, db_session):
        """Test getting an existing organization."""
        user = create_or_update_user(
            db_session,
            email="test@example.com",
            name="Test User",
            github_user_id=12345,
            github_login="testuser",
            avatar_url=None,
        )
        db_session.commit()
        
        org1 = get_or_create_organization(db_session, user, "Test Org")
        db_session.commit()
        
        org2 = get_or_create_organization(db_session, user, "Different Name")
        
        assert org2.id == org1.id
        assert org2.name == "Test Org"

    def test_get_or_create_organization_default_name(self, db_session):
        """Test organization creation with default name."""
        user = create_or_update_user(
            db_session,
            email="test@example.com",
            name="Test User",
            github_user_id=12345,
            github_login="testuser",
            avatar_url=None,
        )
        db_session.commit()
        
        org = get_or_create_organization(db_session, user)
        
        assert org.name == "testuser"

    def test_get_user_by_github_id_found(self, db_session):
        """Test getting user by GitHub ID when found."""
        user = create_or_update_user(
            db_session,
            email="test@example.com",
            name="Test User",
            github_user_id=12345,
            github_login="testuser",
            avatar_url=None,
        )
        db_session.commit()
        
        found_user = get_user_by_github_id(db_session, 12345)
        
        assert found_user is not None
        assert found_user.id == user.id
        assert found_user.github_user_id == 12345

    def test_get_user_by_github_id_not_found(self, db_session):
        """Test getting user by GitHub ID when not found."""
        found_user = get_user_by_github_id(db_session, 99999)
        assert found_user is None

    def test_get_user_by_email_found(self, db_session):
        """Test getting user by email when found."""
        user = create_or_update_user(
            db_session,
            email="test@example.com",
            name="Test User",
            github_user_id=12345,
            github_login="testuser",
            avatar_url=None,
        )
        db_session.commit()
        
        found_user = get_user_by_email(db_session, "test@example.com")
        
        assert found_user is not None
        assert found_user.id == user.id
        assert found_user.email == "test@example.com"

    def test_get_user_by_email_not_found(self, db_session):
        """Test getting user by email when not found."""
        found_user = get_user_by_email(db_session, "notfound@example.com")
        assert found_user is None
