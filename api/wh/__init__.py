"""Webhook handlers for LocalCode."""

from api.wh.github import router as github_router
from api.wh.github_app import router as github_app_router

__all__ = ["github_router", "github_app_router"]
