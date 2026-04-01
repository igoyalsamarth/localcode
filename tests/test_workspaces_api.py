"""Tests for ``/workspaces`` HTTP API."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.jwt_session import create_session_token
from model.enums import MemberRole
from model.tables import OrganizationMember
from tests.db_seed import seed_user, seed_workspace


@pytest.fixture
def workspaces_client():
    from app import app

    return TestClient(app)


@pytest.mark.unit
class TestWorkspacesAPI:
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

    def test_list_requires_auth(self, workspaces_client):
        assert workspaces_client.get("/workspaces").status_code == 401

    def test_list_returns_all_memberships(
        self, workspaces_client, db_session, mock_env
    ):
        u = seed_user(db_session, email="wl@e.com", username="wlister")
        personal = seed_workspace(
            db_session, u, name="wlister's workspace", is_personal=True
        )
        team = seed_workspace(db_session, u, name="Team A", is_personal=False)
        u.github_login = "gh_wl"
        db_session.commit()

        token = create_session_token(
            user_id=u.id, org_id=personal.id, github_login="gh_wl"
        )
        with patch(
            "api.workspaces.session_scope",
            self._patch_session(db_session),
        ):
            r = workspaces_client.get(
                "/workspaces",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        by_id = {row["id"]: row for row in data}
        assert by_id[str(personal.id)]["is_personal"] is True
        assert by_id[str(team.id)]["is_personal"] is False
        assert by_id[str(personal.id)]["role"] == "creator"

    def test_create_team_workspace(self, workspaces_client, db_session, mock_env):
        u = seed_user(db_session, email="wc@e.com", username="wcreate")
        personal = seed_workspace(
            db_session, u, name="wcreate's workspace", is_personal=True
        )
        u.github_login = "gh_wc"
        db_session.commit()
        token = create_session_token(
            user_id=u.id, org_id=personal.id, github_login="gh_wc"
        )
        with patch(
            "api.workspaces.session_scope",
            self._patch_session(db_session),
        ):
            r = workspaces_client.post(
                "/workspaces",
                json={"name": "New Team"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "New Team"
        assert body["is_personal"] is False
        assert body["role"] == "creator"

    def test_switch_workspace_returns_token(
        self, workspaces_client, db_session, mock_env
    ):
        u = seed_user(db_session, email="ws@e.com", username="wswitch")
        personal = seed_workspace(
            db_session, u, name="wswitch's workspace", is_personal=True
        )
        team = seed_workspace(db_session, u, name="T2", is_personal=False)
        u.github_login = "gh_ws"
        db_session.commit()
        token = create_session_token(
            user_id=u.id, org_id=personal.id, github_login="gh_ws"
        )
        with patch(
            "api.workspaces.session_scope",
            self._patch_session(db_session),
        ):
            r = workspaces_client.post(
                "/workspaces/switch",
                json={"workspace_id": str(team.id)},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        assert "token" in r.json()
        new_token = r.json()["token"]
        assert new_token != token

    def test_delete_personal_forbidden(
        self, workspaces_client, db_session, mock_env
    ):
        u = seed_user(db_session, email="wd@e.com", username="wdel")
        personal = seed_workspace(
            db_session, u, name="wdel's workspace", is_personal=True
        )
        u.github_login = "gh_wd"
        db_session.commit()
        token = create_session_token(
            user_id=u.id, org_id=personal.id, github_login="gh_wd"
        )
        with patch(
            "api.workspaces.session_scope",
            self._patch_session(db_session),
        ):
            r = workspaces_client.delete(
                f"/workspaces/{personal.id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 400
        assert "Personal" in r.json()["detail"]

    def test_delete_team_as_creator(
        self, workspaces_client, db_session, mock_env
    ):
        u = seed_user(db_session, email="wd2@e.com", username="wdel2")
        personal = seed_workspace(
            db_session, u, name="wdel2's workspace", is_personal=True
        )
        team = seed_workspace(db_session, u, name="To Delete", is_personal=False)
        u.github_login = "gh_wd2"
        db_session.commit()
        token = create_session_token(
            user_id=u.id, org_id=team.id, github_login="gh_wd2"
        )
        with patch(
            "api.workspaces.session_scope",
            self._patch_session(db_session),
        ):
            r = workspaces_client.delete(
                f"/workspaces/{team.id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200

    def test_add_member_by_username(
        self, workspaces_client, db_session, mock_env
    ):
        admin_u = seed_user(db_session, email="wa@e.com", username="wadmin")
        invitee = seed_user(db_session, email="wi@e.com", username="invitee")
        team = seed_workspace(db_session, admin_u, name="Shared", is_personal=False)
        admin_u.github_login = "gh_wa"
        db_session.commit()
        token = create_session_token(
            user_id=admin_u.id, org_id=team.id, github_login="gh_wa"
        )
        with patch(
            "api.workspaces.session_scope",
            self._patch_session(db_session),
        ):
            r = workspaces_client.post(
                f"/workspaces/{team.id}/members",
                json={"username": "invitee", "role": "user"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["username"] == "invitee"
        assert body["role"] == "user"

    def test_list_members_forbidden_for_user_role(
        self, workspaces_client, db_session, mock_env
    ):
        admin_u = seed_user(db_session, email="wm@e.com", username="wmadmin")
        member_u = seed_user(db_session, email="wm2@e.com", username="wmuser")
        team = seed_workspace(db_session, admin_u, name="RBAC", is_personal=False)
        db_session.add(
            OrganizationMember(
                organization_id=team.id,
                user_id=member_u.id,
                role=MemberRole.user,
            )
        )
        member_u.github_login = "gh_mu"
        db_session.commit()
        token = create_session_token(
            user_id=member_u.id, org_id=team.id, github_login="gh_mu"
        )
        with patch(
            "api.workspaces.session_scope",
            self._patch_session(db_session),
        ):
            r = workspaces_client.get(
                f"/workspaces/{team.id}/members",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 403

    def test_patch_name_requires_creator(
        self, workspaces_client, db_session, mock_env
    ):
        u = seed_user(db_session, email="wp@e.com", username="wpatch")
        team = seed_workspace(db_session, u, name="Old", is_personal=False)
        u.github_login = "gh_wp"
        db_session.commit()
        token = create_session_token(user_id=u.id, org_id=team.id, github_login="gh_wp")
        with patch(
            "api.workspaces.session_scope",
            self._patch_session(db_session),
        ):
            r = workspaces_client.patch(
                f"/workspaces/{team.id}",
                json={"name": "Renamed"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        assert r.json()["name"] == "Renamed"
