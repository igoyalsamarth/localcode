"""API routes for greagent webhook server."""

from api.health import router as health_router
from api.auth import router as auth_router
from api.organization import router as organization_router
from api.connections import router as connections_router
from api.agents import router as agents_router
from api.billing import router as billing_router
from api.dashboard import router as dashboard_router
from api.wh import github_router

__all__ = [
    "health_router",
    "auth_router",
    "organization_router",
    "connections_router",
    "agents_router",
    "billing_router",
    "dashboard_router",
    "github_router",
]
