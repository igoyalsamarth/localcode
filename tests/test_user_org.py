"""Tests for ``require_org_membership``."""

import uuid

import pytest
from fastapi import HTTPException

from api.user_org import require_org_membership, require_workspace_role, role_at_least
from model.enums import MemberRole
from model.tables import Organization, OrganizationMember, User


@pytest.mark.unit
class TestRequireOrgMembership:
    def test_user_not_found(self, db_session):
        missing_id = uuid.uuid4()
        org_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc:
            require_org_membership(db_session, missing_id, org_id)
        assert exc.value.status_code == 404
        assert "User not found" in exc.value.detail

    def test_workspace_not_found(self, db_session):
        user = User(email="solo@example.com", username="solo", auth_provider="github")
        db_session.add(user)
        db_session.commit()
        missing_org = uuid.uuid4()
        with pytest.raises(HTTPException) as exc:
            require_org_membership(db_session, user.id, missing_org)
        assert exc.value.status_code == 404
        assert "Workspace not found" in exc.value.detail

    def test_not_member(self, db_session):
        user = User(email="u@e.com", username="u", auth_provider="github")
        other = User(email="o@e.com", username="o", auth_provider="github")
        db_session.add_all([user, other])
        db_session.flush()
        org = Organization(
            name="W",
            is_personal=False,
            created_by_user_id=other.id,
            owner_user_id=other.id,
        )
        db_session.add(org)
        db_session.flush()
        db_session.add(
            OrganizationMember(
                organization_id=org.id,
                user_id=other.id,
                role=MemberRole.creator,
            )
        )
        db_session.commit()

        with pytest.raises(HTTPException) as exc:
            require_org_membership(db_session, user.id, org.id)
        assert exc.value.status_code == 403

    def test_returns_triple(self, db_session):
        user = User(email="owner@example.com", username="owner", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="My Org",
            is_personal=True,
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
        db_session.commit()

        u2, o2, m = require_org_membership(db_session, user.id, org.id)
        assert u2.id == user.id
        assert o2.id == org.id
        assert m.role == MemberRole.creator


@pytest.mark.unit
class TestRoleAtLeast:
    def test_ordering(self):
        assert role_at_least(MemberRole.creator, MemberRole.admin)
        assert role_at_least(MemberRole.admin, MemberRole.user)
        assert not role_at_least(MemberRole.user, MemberRole.admin)

    def test_require_workspace_role_raises(self, db_session):
        user = User(email="x@e.com", username="x", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="W",
            is_personal=False,
            created_by_user_id=user.id,
            owner_user_id=user.id,
        )
        db_session.add(org)
        db_session.flush()
        m = OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=MemberRole.user,
        )
        db_session.add(m)
        db_session.commit()
        with pytest.raises(HTTPException) as exc:
            require_workspace_role(m, MemberRole.admin)
        assert exc.value.status_code == 403
