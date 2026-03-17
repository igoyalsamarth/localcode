"""API routes for LocalCode webhook server."""

from api.health import router as health_router
from api.wh import github_router

__all__ = ["health_router", "github_router"]
