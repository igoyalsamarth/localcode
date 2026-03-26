"""Tests for session JWT helpers."""

import uuid
from unittest.mock import patch

import jwt
import pytest

from api.jwt_session import (
    JWT_ALGORITHM,
    create_session_token,
    decode_session_token,
    require_jwt_secret,
)


@pytest.mark.unit
class TestJwtSession:
    def test_require_jwt_secret_missing(self):
        with patch("api.jwt_session.JWT_SECRET", ""):
            with pytest.raises(RuntimeError, match="JWT_SECRET"):
                require_jwt_secret()

    def test_create_and_decode_roundtrip(self):
        uid = uuid.uuid4()
        oid = uuid.uuid4()
        token = create_session_token(
            user_id=uid,
            org_id=oid,
            github_login="gh-user",
        )
        payload = decode_session_token(token)
        assert payload["sub"] == str(uid)
        assert payload["org_id"] == str(oid)
        assert payload["github_login"] == "gh-user"
        assert payload["typ"] == "session"
        assert "exp" in payload
        assert "iat" in payload

    def test_decode_rejects_wrong_signature(self):
        uid = uuid.uuid4()
        oid = uuid.uuid4()
        token = create_session_token(
            user_id=uid,
            org_id=oid,
            github_login=None,
        )
        parts = token.rsplit(".", 1)
        tampered = parts[0] + ".badsignature"
        with pytest.raises(jwt.InvalidSignatureError):
            decode_session_token(tampered)
