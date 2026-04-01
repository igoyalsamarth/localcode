"""Pending GitHub install buffer (webhook before SPA callback)."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from api.wh.github import _installation_created
from model.tables import PendingGitHubInstallation
from services.github.installation_sync import complete_installation_for_workspace
from tests.db_seed import seed_user, seed_workspace


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


@pytest.mark.unit
class TestPendingGitHubInstallation:
    def test_installation_created_buffers_repositories(self, db_session):
        data = {
            "action": "created",
            "installation": {
                "id": 999_001,
                "account": {"login": "acme", "type": "User"},
                "permissions": {},
            },
            "repositories": [
                {
                    "id": 42,
                    "name": "r1",
                    "full_name": "acme/r1",
                    "private": False,
                    "default_branch": "main",
                }
            ],
            "sender": {"login": "dev"},
        }
        with patch(
            "api.wh.github.session_scope",
            _patched_session_scope(db_session),
        ):
            r = _installation_created(data)
        assert r["status"] == "buffered"
        row = db_session.get(PendingGitHubInstallation, 999_001)
        assert row is not None
        assert row.sender_login == "dev"
        assert row.account_login == "acme"
        assert row.repositories_json is not None
        assert len(row.repositories_json) == 1
        assert row.repositories_json[0]["name"] == "r1"

    def test_complete_installation_clears_pending(
        self, db_session, mock_env
    ):
        user = seed_user(db_session, email="p@e.com", username="puser")
        org = seed_workspace(db_session, user, name="W", is_personal=False)
        user.github_login = "puser"
        db_session.add(
            PendingGitHubInstallation(
                github_installation_id=999_002,
                sender_login="puser",
                account_login="acme",
                repositories_json=[
                    {
                        "id": 43,
                        "name": "r2",
                        "full_name": "acme/r2",
                        "private": False,
                        "default_branch": "main",
                    }
                ],
            )
        )
        db_session.commit()

        with (
            patch(
                "services.github.installation_sync.fetch_app_installation_json",
                return_value={
                    "account": {
                        "login": "acme",
                        "type": "User",
                        "avatar_url": "https://example.com/a.png",
                    },
                    "permissions": {"contents": "read"},
                },
            ),
            patch(
                "services.github.installation_sync.list_installation_repositories",
                return_value=[],
            ),
            patch(
                "services.github.installation_sync.get_api_token_for_installation",
                return_value="tok",
            ),
            patch(
                "services.github.installation_sync.ensure_greagent_labels_on_repository",
            ),
            patch(
                "services.github.installation_sync.ensure_greagent_review_labels_on_repository",
            ),
        ):
            complete_installation_for_workspace(
                db_session,
                org=org,
                user=user,
                installation_id=999_002,
            )
            db_session.commit()

        assert db_session.get(PendingGitHubInstallation, 999_002) is None
        from model.tables import Repository

        repos = db_session.query(Repository).filter_by(organization_id=org.id).all()
        assert len(repos) == 1
        assert repos[0].github_repo_id == 43
