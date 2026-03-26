"""Tests for ``require_user_and_owned_org``."""

import uuid

import pytest
from fastapi import HTTPException

from api.user_org import require_user_and_owned_org
from model.tables import Organization, User


@pytest.mark.unit
class TestRequireUserAndOwnedOrg:
    def test_user_not_found(self, db_session):
        missing_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc:
            require_user_and_owned_org(db_session, missing_id)
        assert exc.value.status_code == 404
        assert "User not found" in exc.value.detail

    def test_organization_not_found(self, db_session):
        user = User(email="solo@example.com", auth_provider="github")
        db_session.add(user)
        db_session.commit()

        with pytest.raises(HTTPException) as exc:
            require_user_and_owned_org(db_session, user.id)
        assert exc.value.status_code == 404
        assert "Organization not found" in exc.value.detail

    def test_returns_user_and_org(self, db_session):
        user = User(email="owner@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(name="My Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.commit()

        u2, o2 = require_user_and_owned_org(db_session, user.id)
        assert u2.id == user.id
        assert o2.id == org.id
        assert o2.owner_user_id == user.id
