"""GitHub App install URL and SPA callback (workspace-scoped)."""

from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.jwt_session import create_session_token
from tests.db_seed import seed_user, seed_workspace


@pytest.fixture
def connections_client():
    from app import app

    return TestClient(app)


@pytest.mark.unit
class TestConnectionsGitHubInstall:
    def test_install_url_contains_workspace_state(
        self, connections_client, db_session, mock_env
    ):
        user = seed_user(db_session, email="gh@e.com", username="ghuser")
        org = seed_workspace(db_session, user, name="Team", is_personal=False)
        user.github_login = "ghuser"
        db_session.commit()
        token = create_session_token(
            user_id=user.id, org_id=org.id, github_login="ghuser"
        )
        with (
            patch("api.connections.GITHUB_APP_SLUG", "test-github-app"),
            patch(
                "api.connections.session_scope",
                _patched_session_scope(db_session),
            ),
        ):
            r = connections_client.post(
                "/connections/github/install",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        url = r.json()["installUrl"]
        assert str(org.id) in url
        assert "state=" in url

    def test_callback_rejects_state_mismatch(
        self, connections_client, db_session, mock_env
    ):
        user = seed_user(db_session, email="gh2@e.com", username="ghuser2")
        org = seed_workspace(db_session, user, name="W1", is_personal=False)
        other = uuid4()
        user.github_login = "ghuser2"
        db_session.commit()
        token = create_session_token(
            user_id=user.id, org_id=org.id, github_login="ghuser2"
        )
        with patch(
            "api.connections.session_scope",
            _patched_session_scope(db_session),
        ):
            r = connections_client.post(
                "/connections/github/installation/callback",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "installation_id": 99_001,
                    "state": str(other),
                },
            )
        assert r.status_code == 403

    def test_callback_completes_when_state_matches(
        self, connections_client, db_session, mock_env
    ):
        user = seed_user(db_session, email="gh3@e.com", username="ghuser3")
        org = seed_workspace(db_session, user, name="W2", is_personal=False)
        user.github_login = "ghuser3"
        db_session.commit()
        token = create_session_token(
            user_id=user.id, org_id=org.id, github_login="ghuser3"
        )
        with (
            patch(
                "api.connections.session_scope",
                _patched_session_scope(db_session),
            ),
            patch(
                "api.connections.complete_installation_for_workspace",
                lambda *a, **k: None,
            ),
        ):
            r = connections_client.post(
                "/connections/github/installation/callback",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "installation_id": 99_002,
                    "state": str(org.id),
                },
            )
        assert r.status_code == 200
        assert r.json()["status"] == "connected"


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
