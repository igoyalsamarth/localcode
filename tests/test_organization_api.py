"""Tests for ``/organization`` HTTP API (single owner)."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.jwt_session import create_session_token
from tests.db_seed import seed_user, seed_workspace


@pytest.fixture
def org_client():
    from app import app

    return TestClient(app)


@pytest.mark.unit
class TestOrganizationAPI:
    @staticmethod
    def _patch_session(db_session):
        @contextmanager
        def cm():
            try:
                yield db_session
                db_session.commit()
            except Exception:
                db_session.rollback()
                raise

        return cm

    def test_get_requires_auth(self, org_client):
        assert org_client.get("/organization").status_code == 401

    def test_get_returns_current_org(self, org_client, db_session, mock_env):
        u = seed_user(db_session, email="og@e.com", username="oguser")
        org = seed_workspace(
            db_session, u, name="oguser's workspace", is_personal=True
        )
        u.github_login = "gh_og"
        db_session.commit()
        token = create_session_token(
            user_id=u.id, org_id=org.id, github_login="gh_og"
        )
        with patch(
            "api.organization.session_scope",
            self._patch_session(db_session),
        ):
            r = org_client.get(
                "/organization",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == str(org.id)
        assert body["name"] == "oguser's workspace"
        assert body["is_personal"] is True
        assert "role" not in body

    def test_patch_name(self, org_client, db_session, mock_env):
        u = seed_user(db_session, email="op@e.com", username="opatch")
        team = seed_workspace(db_session, u, name="Old", is_personal=False)
        u.github_login = "gh_op"
        db_session.commit()
        token = create_session_token(user_id=u.id, org_id=team.id, github_login="gh_op")
        with patch(
            "api.organization.session_scope",
            self._patch_session(db_session),
        ):
            r = org_client.patch(
                "/organization",
                json={"name": "Renamed"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        assert r.json()["name"] == "Renamed"
