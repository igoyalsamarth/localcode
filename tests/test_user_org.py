"""Tests for ``require_org_membership`` (organization owner only)."""

import uuid

import pytest
from fastapi import HTTPException

from api.user_org import require_org_membership
from model.tables import Organization, User


@pytest.mark.unit
class TestRequireOrgMembership:
    def test_user_not_found(self, db_session):
        missing_id = uuid.uuid4()
        org_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc:
            require_org_membership(db_session, missing_id, org_id)
        assert exc.value.status_code == 404
        assert "User not found" in exc.value.detail

    def test_organization_not_found(self, db_session):
        user = User(email="solo@example.com", username="solo", auth_provider="github")
        db_session.add(user)
        db_session.commit()
        missing_org = uuid.uuid4()
        with pytest.raises(HTTPException) as exc:
            require_org_membership(db_session, user.id, missing_org)
        assert exc.value.status_code == 404
        assert "Organization not found" in exc.value.detail

    def test_not_owner(self, db_session):
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
        db_session.commit()

        with pytest.raises(HTTPException) as exc:
            require_org_membership(db_session, user.id, org.id)
        assert exc.value.status_code == 403

    def test_returns_user_and_org(self, db_session):
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
        db_session.commit()

        u2, o2 = require_org_membership(db_session, user.id, org.id)
        assert u2.id == user.id
        assert o2.id == org.id
