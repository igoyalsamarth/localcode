"""GitHub ``installation`` webhook: bind to user's single organization."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import select

from api.wh.github import _installation_created
from model.tables import GitHubInstallation
from services.user_service import get_or_create_personal_workspace
from tests.db_seed import seed_user


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
class TestGithubWebhookInstallationCreated:
    def test_installation_created_ignored_without_matching_user(self, db_session):
        data = {
            "action": "created",
            "installation": {
                "id": 777_001,
                "account": {"login": "ghost", "type": "User"},
                "permissions": {},
            },
            "sender": {"login": "ghost"},
            "repositories": [],
        }
        with patch("api.wh.github.session_scope", _patched_session_scope(db_session)):
            r = _installation_created(data)
        assert r["status"] == "ignored"
        assert r["reason"] == "unknown_installer"

    def test_installation_created_calls_complete_when_user_known(
        self, db_session, mock_env
    ):
        user = seed_user(db_session, email="wh@e.com", username="gh_wh")
        user.github_login = "gh_wh"
        db_session.commit()
        get_or_create_personal_workspace(db_session, user)
        db_session.commit()

        data = {
            "action": "created",
            "installation": {
                "id": 777_002,
                "account": {"login": "gh_wh", "type": "User"},
                "permissions": {},
            },
            "sender": {"login": "gh_wh"},
            "repositories": [],
        }
        with (
            patch("api.wh.github.session_scope", _patched_session_scope(db_session)),
            patch(
                "api.wh.github.complete_installation_for_workspace",
                lambda *a, **k: None,
            ),
        ):
            r = _installation_created(data)
        assert r["status"] == "received"

        stmt = select(GitHubInstallation).where(
            GitHubInstallation.github_installation_id == 777_002
        )
        assert db_session.execute(stmt).scalar_one_or_none() is None

    def test_installation_created_updates_existing_row(self, db_session, mock_env):
        user = seed_user(db_session, email="wh2@e.com", username="gh_wh2")
        user.github_login = "gh_wh2"
        db_session.commit()
        org = get_or_create_personal_workspace(db_session, user)
        db_session.add(
            GitHubInstallation(
                organization_id=org.id,
                github_installation_id=777_003,
                account_name="old",
            )
        )
        db_session.commit()

        data = {
            "action": "created",
            "installation": {
                "id": 777_003,
                "account": {"login": "gh_wh2", "type": "User", "avatar_url": "http://a"},
                "permissions": {"metadata": "read"},
            },
            "sender": {"login": "gh_wh2"},
            "repositories": [],
        }
        with patch("api.wh.github.session_scope", _patched_session_scope(db_session)):
            r = _installation_created(data)
        assert r["status"] == "received"
        db_session.expire_all()
        stmt = select(GitHubInstallation).where(
            GitHubInstallation.github_installation_id == 777_003
        )
        row = db_session.execute(stmt).scalar_one()
        assert row.account_name == "gh_wh2"
