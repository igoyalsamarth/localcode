"""Integration tests for agents API endpoints."""

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from api.jwt_session import create_session_token
from model.enums import AgentType
from model.tables import Agent, Organization, Repository, User


@pytest.mark.unit
class TestAgentsAPIIntegration:
    """Integration tests for /agents routes (coder, reviewer, usage)."""

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
    def _seed_org_with_repo(db_session):
        user = User(
            email="agents-api@example.com",
            username="agentsapi",
            auth_provider="github",
        )
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="Agents API Org",
            is_personal=False,
            created_by_user_id=user.id,
            owner_user_id=user.id,
        )
        db_session.add(org)
        db_session.flush()
        repo = Repository(
            organization_id=org.id,
            github_repo_id=88_001,
            name="svc",
            owner="acme",
            default_branch="main",
        )
        db_session.add(repo)
        db_session.commit()
        return user, org, repo

    @pytest.fixture
    def client(self):
        from app import app

        return TestClient(app)

    def test_agents_routes_registered(self, client):
        routes = [route.path for route in client.app.routes]
        assert any(r.startswith("/agents/") for r in routes)

    def test_get_coder_settings_requires_auth(self, client):
        r = client.get("/agents/coder/settings")
        assert r.status_code == 401

    def test_get_coder_settings_returns_json(self, client):
        r = client.get("/agents/coder/settings")
        assert "application/json" in r.headers["content-type"]

    def test_get_coder_settings_ok_with_membership(
        self, client, db_session, mock_env
    ):
        user, org, _repo = self._seed_org_with_repo(db_session)
        token = create_session_token(
            user_id=user.id,
            org_id=org.id,
            github_login="agentsapi",
        )
        with patch(
            "api.agents.session_scope",
            self._patched_session_scope(db_session),
        ):
            r = client.get(
                "/agents/coder/settings",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        data = r.json()
        assert "repositories" in data
        assert "configurations" in data
        agents = (
            db_session.query(Agent)
            .filter_by(organization_id=org.id, type=AgentType.code)
            .all()
        )
        assert len(agents) == 1

    def test_get_reviewer_settings_requires_auth(self, client):
        r = client.get("/agents/reviewer/settings")
        assert r.status_code == 401

    def test_get_usage_requires_auth(self, client):
        r = client.get("/agents/usage")
        assert r.status_code == 401

    def test_put_coder_repository_requires_auth(self, client):
        r = client.put(
            "/agents/coder/repositories/88001",
            json={"enabled": True, "mode": "auto"},
        )
        assert r.status_code == 401

    def test_put_coder_repository_requires_admin(
        self, client, db_session, mock_env
    ):
        """Creator has admin+ and can update repository config."""
        user, org, repo = self._seed_org_with_repo(db_session)
        token = create_session_token(
            user_id=user.id,
            org_id=org.id,
            github_login="agentsapi",
        )
        with patch(
            "api.agents.session_scope",
            self._patched_session_scope(db_session),
        ):
            r = client.put(
                f"/agents/coder/repositories/{repo.github_repo_id}",
                json={"enabled": True, "mode": "auto"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True
        assert body["mode"] == "auto"

    def test_agents_collection_post_not_defined(self, client):
        """No POST /agents route."""
        r = client.post("/agents", json={})
        assert r.status_code == 404
