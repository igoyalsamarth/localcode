"""HS256 session JWTs issued after GitHub OAuth (not GitHub App installation JWTs)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from constants import JWT_EXPIRE_DAYS, JWT_SECRET

JWT_ALGORITHM = "HS256"


def require_jwt_secret() -> str:
    if not JWT_SECRET:
        raise RuntimeError(
            "JWT_SECRET is not set. Add a long random string to your environment."
        )
    return JWT_SECRET


def create_session_token(
    *,
    user_id: UUID,
    org_id: UUID,
    github_login: str | None,
) -> str:
    """Create a short-lived app session JWT (API Bearer token)."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=JWT_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "github_login": github_login,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "typ": "session",
    }
    return jwt.encode(payload, require_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_session_token(token: str) -> dict:
    """Validate and decode a session JWT."""
    return jwt.decode(
        token,
        require_jwt_secret(),
        algorithms=[JWT_ALGORITHM],
        options={"require": ["exp", "sub"]},
    )
