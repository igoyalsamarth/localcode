"""Tests for user service."""

import pytest

from constants import SIGNUP_PROMO_WALLET_USD

from services.user_service import (
    create_or_update_user,
    create_team_workspace,
    get_or_create_personal_workspace,
    get_user_by_email,
    get_user_by_github_id,
)
from model.tables import User, Organization, OrganizationMember
from model.enums import MemberRole


@pytest.mark.unit
class TestUserService:
    def test_create_or_update_user_new(self, db_session):
        user = create_or_update_user(
            db_session,
            email="test@example.com",
            name="Test User",
            github_user_id=12345,
            github_login="testuser",
            avatar_url="https://github.com/avatar.png",
        )

        assert user.email == "test@example.com"
        assert user.username == "testuser"
        assert user.github_user_id == 12345
        assert user.auth_provider == "github"

    def test_create_or_update_user_existing_updates_username(self, db_session):
        user1 = create_or_update_user(
            db_session,
            email="test@example.com",
            name="Test User",
            github_user_id=12345,
            github_login="testuser",
            avatar_url=None,
        )
        db_session.commit()

        user2 = create_or_update_user(
            db_session,
            email="updated@example.com",
            name="Updated User",
            github_user_id=12345,
            github_login="updateduser",
            avatar_url=None,
        )

        assert user2.id == user1.id
        assert user2.username == "updateduser"

    def test_get_or_create_personal_workspace_new(self, db_session):
        user = create_or_update_user(
            db_session,
            email="test@example.com",
            name="Test User",
            github_user_id=12345,
            github_login="testuser",
            avatar_url=None,
        )
        db_session.commit()

        org = get_or_create_personal_workspace(db_session, user)

        assert org.is_personal is True
        assert org.created_by_user_id == user.id
        assert org.owner_user_id == user.id
        assert org.name == "testuser's workspace"

        member = db_session.query(OrganizationMember).filter_by(
            organization_id=org.id,
            user_id=user.id,
        ).first()
        assert member is not None
        assert member.role == MemberRole.creator
        assert org.promotional_balance_usd == SIGNUP_PROMO_WALLET_USD
        assert user.onboarded is True

    def test_get_or_create_personal_workspace_idempotent(self, db_session):
        user = create_or_update_user(
            db_session,
            email="test@example.com",
            name="Test User",
            github_user_id=12345,
            github_login="testuser",
            avatar_url=None,
        )
        db_session.commit()

        org1 = get_or_create_personal_workspace(db_session, user)
        db_session.commit()
        org2 = get_or_create_personal_workspace(db_session, user)

        assert org2.id == org1.id

    def test_create_team_workspace_no_promo(self, db_session):
        user = create_or_update_user(
            db_session,
            email="test@example.com",
            name="Test User",
            github_user_id=12345,
            github_login="testuser",
            avatar_url=None,
        )
        db_session.commit()

        org = create_team_workspace(db_session, user, "Team A")

        assert org.is_personal is False
        assert org.name == "Team A"
        assert org.promotional_balance_usd == 0
        assert org.promotional_balance_expires_at is None

    def test_get_user_by_github_id_found(self, db_session):
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

    def test_get_user_by_github_id_not_found(self, db_session):
        assert get_user_by_github_id(db_session, 99999) is None

    def test_get_user_by_email_found(self, db_session):
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

    def test_get_user_by_email_not_found(self, db_session):
        assert get_user_by_email(db_session, "notfound@example.com") is None
