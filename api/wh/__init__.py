"""Webhook handlers for Greagent."""

from api.wh.github import router as github_router

__all__ = ["github_router"]
