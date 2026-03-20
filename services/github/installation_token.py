"""
GitHub App **installation access tokens** for REST API and for ``git`` / ``gh`` (via ``GH_TOKEN``).
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import jwt
import requests
from sqlalchemy import select

from constants import (
    GITHUB_APP_CLIENT_ID,
    GITHUB_APP_ID,
    GITHUB_APP_PRIVATE_KEY,
)
from db import session_scope
from logger import get_logger
from model.tables import GitHubInstallation, Organization, Repository

logger = get_logger(__name__)

_GITHUB_API = "https://api.github.com"
_cache: dict[int, tuple[str, float]] = {}
_lock = threading.Lock()


def _private_key_pem() -> str:
    return (GITHUB_APP_PRIVATE_KEY or "").replace("\\n", "\n")


def app_credentials_configured() -> bool:
    """Private key plus issuer: GitHub recommends ``iss`` = Client ID; App ID also works."""
    has_issuer = bool(GITHUB_APP_CLIENT_ID or GITHUB_APP_ID)
    return bool(GITHUB_APP_PRIVATE_KEY and has_issuer)


def _jwt_iss_claim() -> str | int:
    """
    ``iss`` for GitHub App JWTs: Client ID (string, recommended) or numeric App ID.

    See: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app
    """
    if GITHUB_APP_CLIENT_ID.strip():
        return GITHUB_APP_CLIENT_ID.strip()
    if GITHUB_APP_ID.strip():
        return int(GITHUB_APP_ID.strip())
    raise RuntimeError("Set GITHUB_APP_CLIENT_ID (recommended) or GITHUB_APP_ID")


def create_app_jwt() -> str:
    if not app_credentials_configured():
        raise RuntimeError(
            "GITHUB_APP_PRIVATE_KEY and GITHUB_APP_CLIENT_ID (or GITHUB_APP_ID) are required"
        )
    now = int(time.time())
    payload: dict[str, Any] = {
        "iat": now - 60,
        "exp": now + (9 * 60),
        "iss": _jwt_iss_claim(),
    }
    encoded = jwt.encode(payload, _private_key_pem(), algorithm="RS256")
    if isinstance(encoded, bytes):
        return encoded.decode("utf-8")
    return encoded


def _parse_expires_at(raw: str) -> float:
    s = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def get_installation_access_token(installation_id: int) -> str:
    """Return a valid token for this installation, using a short-lived in-memory cache."""
    now = time.time()
    with _lock:
        hit = _cache.get(installation_id)
        if hit and now < hit[1] - 120:
            return hit[0]

    jwt_token = create_app_jwt()
    url = f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens"
    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    tok = data["token"]
    exp_raw = data.get("expires_at")
    exp = _parse_expires_at(exp_raw) if isinstance(exp_raw, str) else now + 3600

    with _lock:
        _cache[installation_id] = (tok, exp)
    return tok


def get_github_installation_id_for_repo(owner: str, repo_name: str) -> int | None:
    """Resolve GitHub ``installation_id`` for a repository from the DB."""
    with session_scope() as session:
        stmt = (
            select(Organization)
            .join(Repository, Repository.organization_id == Organization.id)
            .where(
                Repository.owner == owner,
                Repository.name == repo_name,
            )
        )
        org = session.execute(stmt).scalar_one_or_none()
        if not org:
            return None
        if org.github_installation_id is not None:
            return int(org.github_installation_id)
        stmt = select(GitHubInstallation.github_installation_id).where(
            GitHubInstallation.organization_id == org.id
        ).limit(1)
        row = session.execute(stmt).scalar_one_or_none()
        return int(row) if row is not None else None


def get_api_token_for_installation(installation_id: int) -> str:
    """Installation token when the webhook already provides ``installation_id``."""
    if not app_credentials_configured():
        raise RuntimeError(
            "GitHub App JWT credentials missing: set GITHUB_APP_PRIVATE_KEY and "
            "GITHUB_APP_CLIENT_ID (or GITHUB_APP_ID)"
        )
    return get_installation_access_token(installation_id)


def get_api_token_for_repo(owner: str, repo_name: str) -> str:
    """Installation access token for REST + git for this repository."""
    if not app_credentials_configured():
        raise RuntimeError(
            "GitHub App JWT credentials missing: set GITHUB_APP_PRIVATE_KEY and "
            "GITHUB_APP_CLIENT_ID (or GITHUB_APP_ID)"
        )
    iid = get_github_installation_id_for_repo(owner, repo_name)
    if iid is None:
        raise RuntimeError(
            f"No GitHub App installation linked in the database for {owner}/{repo_name}. "
            "Install the app and ensure installation webhooks have synced."
        )
    return get_installation_access_token(iid)


@contextmanager
def installation_token_env(token: str):
    """
    Expose the installation token to subprocesses as ``GH_TOKEN`` (``gh`` / scripts).

    GitHub CLI reads ``GH_TOKEN``; we avoid the old ``GITHUB_TOKEN`` PAT convention.
    """
    previous = os.environ.get("GH_TOKEN")
    os.environ["GH_TOKEN"] = token
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("GH_TOKEN", None)
        else:
            os.environ["GH_TOKEN"] = previous
