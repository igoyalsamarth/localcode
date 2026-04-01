"""Tests for reviewer agent settings endpoints (patched DB session)."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.jwt_session import create_session_token
from model.enums import AgentType, MemberRole
from model.tables import Agent, Organization, OrganizationMember, Repository, User


@pytest.fixture
def reviewer_settings_client():
    from app import app

    return TestClient(app)


@pytest.mark.unit
class TestAgentsReviewerSettingsAPI:
    @staticmethod
    def _patched_session_scope(session):
        @contextmanager
        def cm():
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

        return cm

    @staticmethod
    def _seed_org_repo(db_session):
        user = User(
            email="rev-settings@example.com",
            username="revsettings",
            auth_provider="github",
        )
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="Rev Org",
            is_personal=False,
            created_by_user_id=user.id,
            owner_user_id=user.id,
        )
        db_session.add(org)
        db_session.flush()
        db_session.add(
            OrganizationMember(
                organization_id=org.id,
                user_id=user.id,
                role=MemberRole.creator,
            )
        )
        db_session.flush()
        repo = Repository(
            organization_id=org.id,
            github_repo_id=77_007,
            name="svc",
            owner="acme",
            default_branch="main",
        )
        db_session.add(repo)
        db_session.commit()
        return user, org

    def test_get_reviewer_settings_shape(
        self, reviewer_settings_client, db_session, mock_env
    ):
        user, org = self._seed_org_repo(db_session)
        token = create_session_token(
            user_id=user.id,
            org_id=org.id,
            github_login=None,
        )

        with patch(
            "api.agents.session_scope",
            self._patched_session_scope(db_session),
        ):
            r = reviewer_settings_client.get(
                "/agents/reviewer/settings",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert r.status_code == 200
        data = r.json()
        assert "repositories" in data
        assert "configurations" in data
        assert len(data["repositories"]) == 1
        assert data["repositories"][0]["fullName"] == "acme/svc"
        assert len(data["configurations"]) == 1
        assert data["configurations"][0]["repositoryId"] == 77_007
        assert data["configurations"][0]["enabled"] is True
        assert data["configurations"][0]["mode"] == "auto"

        agents = db_session.query(Agent).filter_by(
            organization_id=org.id, type=AgentType.review
        ).all()
        assert len(agents) == 1
        assert agents[0].name == "Review Agent"

    def test_put_reviewer_repository_config(
        self, reviewer_settings_client, db_session, mock_env
    ):
        user, org = self._seed_org_repo(db_session)
        token = create_session_token(
            user_id=user.id,
            org_id=org.id,
            github_login=None,
        )

        with patch(
            "api.agents.session_scope",
            self._patched_session_scope(db_session),
        ):
            with patch("api.agents.ensure_greagent_review_labels_on_repository"):
                r = reviewer_settings_client.put(
                    "/agents/reviewer/repositories/77007",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"enabled": True, "mode": "on_assignment"},
                )

        assert r.status_code == 200
        assert r.json() == {
            "repositoryId": 77007,
            "enabled": True,
            "mode": "on_assignment",
        }
