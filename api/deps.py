"""FastAPI dependencies (auth)."""

from __future__ import annotations

from uuid import UUID

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.jwt_session import decode_session_token

security = HTTPBearer(auto_error=False)


def get_current_user_id(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
) -> UUID:
    """Require a valid Bearer session JWT; return the user id (``sub``)."""
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_session_token(creds.credentials)
        return UUID(str(payload["sub"]))
    except RuntimeError:
        raise HTTPException(
            status_code=500,
            detail="JWT_SECRET is not configured on the server",
        ) from None
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired") from None
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid token") from None
