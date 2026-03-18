"""GitHub OAuth authentication routes."""

from typing import Optional

import requests
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from constants import (
    GITHUB_CLIENT_ID,
    GITHUB_CLIENT_SECRET,
    GITHUB_REDIRECT_URI,
    CLIENT_URL,
)
from db import session_scope
from services import create_or_update_user, get_or_create_organization
from logger import get_logger
from urllib.parse import urlencode, urljoin

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/login")
async def github_login(redirect_to: Optional[str] = Query(None)):
    """
    Initiate GitHub OAuth flow.

    Redirects user to GitHub authorization page.

    Args:
        redirect_to: Optional URL to redirect to after successful authentication
    """
    if not GITHUB_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GITHUB_CLIENT_ID not configured")

    scope = "repo,user:email,read:org"

    state = redirect_to if redirect_to else ""

    github_auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={GITHUB_REDIRECT_URI}"
        f"&scope={scope}"
        f"&state={state}"
    )

    logger.info("Redirecting to GitHub OAuth")
    return RedirectResponse(url=github_auth_url)


@router.get("/github/callback")
async def github_callback(code: str = Query(...), state: Optional[str] = Query(None)):
    """
    Handle GitHub OAuth callback.

    Exchanges authorization code for access token.

    Args:
        code: Authorization code from GitHub
        state: Optional state parameter (can contain redirect URL)
    """
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=500, detail="GitHub OAuth not properly configured"
        )

    try:
        token_response = requests.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": GITHUB_REDIRECT_URI,
            },
            timeout=10,
        )
        token_response.raise_for_status()
        token_data = token_response.json()

        if "error" in token_data:
            logger.error(f"GitHub OAuth error: {token_data}")
            raise HTTPException(
                status_code=400,
                detail=f"GitHub OAuth error: {token_data.get('error_description', token_data['error'])}",
            )

        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=400, detail="No access token received from GitHub"
            )

        user_response = requests.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=10,
        )
        user_response.raise_for_status()
        user_data = user_response.json()

        github_user_id = user_data.get("id")
        github_login = user_data.get("login")
        name = user_data.get("name")
        email = user_data.get("email")
        avatar_url = user_data.get("avatar_url")

        if not email:
            email_response = requests.get(
                "https://api.github.com/user/emails",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
                timeout=10,
            )
            email_response.raise_for_status()
            emails = email_response.json()
            primary_email = next((e for e in emails if e.get("primary")), None)
            if primary_email:
                email = primary_email.get("email")

        if not email:
            raise HTTPException(
                status_code=400,
                detail="Unable to retrieve email from GitHub. Please make sure your email is public or grant email scope.",
            )

        logger.info(f"User authenticated: {github_login}")

        with session_scope() as session:
            user = create_or_update_user(
                session=session,
                email=email,
                name=name,
                github_user_id=github_user_id,
                github_login=github_login,
                avatar_url=avatar_url,
            )

            organization = get_or_create_organization(
                session=session,
                user=user,
            )

            session.commit()

            logger.info(
                f"User synced to database: {user.id}, Organization: {organization.id}"
            )

        # TODO: Create JWT token for session management
        # For now, pass user data as query parameters (consider using JWT in production)

        redirect_url = state if state else f"{CLIENT_URL}/auth/callback"

        # Append user and org info to redirect URL
        params = {
            "user_id": str(user.id),
            "github_login": github_login,
            "org_id": str(organization.id),
            "org_name": organization.name,
            "access_token": access_token,
        }

        redirect_url_with_params = f"{redirect_url}?{urlencode(params)}"

        logger.info(f"Redirecting to client: {redirect_url}")
        return RedirectResponse(url=redirect_url_with_params)

    except requests.RequestException as e:
        logger.exception(f"Failed to complete GitHub OAuth: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to authenticate with GitHub: {str(e)}"
        )


@router.get("/logout")
async def logout():
    """
    Logout endpoint.

    TODO: Implement session/token invalidation
    """
    logger.info("User logged out")
    return {"status": "logged_out"}
