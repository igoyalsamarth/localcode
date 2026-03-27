"""API routes for greagent webhook server."""

from api.health import router as health_router
from api.auth import router as auth_router
from api.onboarding import router as onboarding_router
from api.connections import router as connections_router
from api.agents import router as agents_router
from api.wh import github_router

__all__ = [
    "health_router",
    "auth_router",
    "onboarding_router",
    "connections_router",
    "agents_router",
    "github_router",
]
