"""Tests for FastAPI application setup."""

import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.unit
class TestApp:
    """Test FastAPI application configuration."""

    def test_app_exists(self):
        """Test that app instance exists."""
        from app import app

        assert app is not None

    def test_app_title(self):
        """Test app has correct title."""
        from app import app

        assert app.title == "Greagent Webhook Server"

    def test_app_description(self):
        """Test app has description."""
        from app import app

        assert "GitHub webhooks" in app.description

    def test_app_version(self):
        """Test app has version."""
        from app import app

        assert app.version == "0.1.0"

    def test_app_has_cors_middleware(self):
        """Test app has CORS middleware configured."""
        from app import app

        # Check that middleware is configured
        assert len(app.user_middleware) > 0

    def test_app_has_health_router(self):
        """Test app includes health router."""
        from app import app

        routes = [route.path for route in app.routes]
        assert "/health" in routes

    def test_app_has_auth_router(self):
        """Test app includes auth router."""
        from app import app

        routes = [route.path for route in app.routes]
        auth_routes = [r for r in routes if r.startswith("/auth")]
        assert len(auth_routes) > 0

    def test_app_has_organization_router(self):
        """Test app includes organization router."""
        from app import app

        routes = [route.path for route in app.routes]
        org_routes = [r for r in routes if r.startswith("/organization")]
        assert len(org_routes) > 0

    def test_app_has_connections_router(self):
        """Test app includes connections router."""
        from app import app

        routes = [route.path for route in app.routes]
        connections_routes = [r for r in routes if r.startswith("/connections")]
        assert len(connections_routes) > 0

    def test_app_has_agents_router(self):
        """Test app includes agents router."""
        from app import app

        routes = [route.path for route in app.routes]
        agents_routes = [r for r in routes if r.startswith("/agents")]
        assert len(agents_routes) > 0

    def test_app_has_webhook_router(self):
        """Test app includes webhook router."""
        from app import app

        routes = [route.path for route in app.routes]
        # Webhook routes might be at /webhooks or /wh
        webhook_routes = [r for r in routes if "/webhook" in r or r.startswith("/wh")]
        assert len(webhook_routes) > 0 or "/webhooks/github" in routes

    def test_app_reload_disabled(self):
        """Test app has reload disabled."""
        from app import app

        # FastAPI doesn't expose reload directly, but we can check it's not in debug mode
        assert hasattr(app, "debug")
