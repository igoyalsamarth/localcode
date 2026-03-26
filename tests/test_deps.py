"""Tests for FastAPI auth dependencies."""

import uuid
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import HTTPException

from api.deps import get_current_user_id
from api.jwt_session import JWT_ALGORITHM, create_session_token, require_jwt_secret
from fastapi.security import HTTPAuthorizationCredentials


@pytest.mark.unit
class TestGetCurrentUserId:
    """Tests for ``get_current_user_id``."""

    def test_missing_credentials_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            get_current_user_id(None)
        assert exc.value.status_code == 401
        assert "Not authenticated" in exc.value.detail

    def test_empty_bearer_token_raises_401(self):
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="")
        with pytest.raises(HTTPException) as exc:
            get_current_user_id(creds)
        assert exc.value.status_code == 401

    def test_invalid_token_raises_401(self):
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt")
        with pytest.raises(HTTPException) as exc:
            get_current_user_id(creds)
        assert exc.value.status_code == 401

    def test_expired_token_raises_401(self):
        import time
        from datetime import datetime, timezone

        uid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(uid),
            "exp": int(now.timestamp()) - 10,
            "iat": int(now.timestamp()) - 20,
        }
        token = jwt.encode(payload, require_jwt_secret(), algorithm=JWT_ALGORITHM)
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with pytest.raises(HTTPException) as exc:
            get_current_user_id(creds)
        assert exc.value.status_code == 401
        assert "expired" in exc.value.detail.lower()

    def test_valid_token_returns_user_uuid(self):
        uid = uuid.uuid4()
        oid = uuid.uuid4()
        token = create_session_token(
            user_id=uid,
            org_id=oid,
            github_login="tester",
        )
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        assert get_current_user_id(creds) == uid
