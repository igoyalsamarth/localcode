"""Integration tests for auth API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from urllib.parse import parse_qs, unquote_plus, urlparse


@pytest.mark.unit
class TestAuthAPIIntegration:
    """Integration tests for authentication endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from app import app
        return TestClient(app)

    def test_login_endpoint_exists(self, client):
        """Test login endpoint is accessible."""
        with patch("api.auth.GITHUB_CLIENT_ID", "test_client_id"):
            response = client.get("/auth/login", follow_redirects=False)
            
            assert response.status_code in [200, 307, 302]

    def test_login_redirects_to_github(self, client):
        """Test login redirects to GitHub OAuth."""
        with patch("api.auth.GITHUB_CLIENT_ID", "test_client_id"):
            response = client.get("/auth/login", follow_redirects=False)
            
            assert response.status_code in [307, 302]
            assert "location" in response.headers
            assert "github.com" in response.headers["location"]

    def test_login_includes_client_id(self, client):
        """Test login redirect includes client ID."""
        with patch("api.auth.GITHUB_CLIENT_ID", "test_client_123"):
            response = client.get("/auth/login", follow_redirects=False)
            
            location = response.headers.get("location", "")
            assert "client_id=test_client_123" in location

    def test_login_includes_redirect_uri(self, client):
        """Test login redirect includes redirect URI."""
        with patch("api.auth.GITHUB_CLIENT_ID", "test_client_id"):
            with patch("api.auth.GITHUB_REDIRECT_URI", "http://test.com/callback"):
                response = client.get("/auth/login", follow_redirects=False)
                
                location = response.headers.get("location", "")
                assert "redirect_uri=" in location

    def test_login_includes_scope(self, client):
        """OAuth asks only for identity scopes (no repo or org read)."""
        with patch("api.auth.GITHUB_CLIENT_ID", "test_client_id"):
            response = client.get("/auth/login", follow_redirects=False)

            location = response.headers.get("location", "")
            assert "scope=" in location
            q = parse_qs(urlparse(location).query)
            scope = unquote_plus(q.get("scope", [""])[0])
            assert "read:user" in scope
            assert "user:email" in scope
            assert "repo" not in scope
            assert "read:org" not in scope

    def test_login_with_redirect_to_parameter(self, client):
        """Test login with redirect_to parameter."""
        with patch("api.auth.GITHUB_CLIENT_ID", "test_client_id"):
            response = client.get(
                "/auth/login?redirect_to=/dashboard",
                follow_redirects=False
            )
            
            location = response.headers.get("location", "")
            assert "state=" in location

    def test_login_without_client_id_fails(self, client):
        """Test login fails without GITHUB_CLIENT_ID."""
        with patch("api.auth.GITHUB_CLIENT_ID", ""):
            response = client.get("/auth/login")
            
            assert response.status_code == 500
            data = response.json()
            assert "detail" in data
            assert "GITHUB_CLIENT_ID" in data["detail"]

    def test_logout_endpoint_exists(self, client):
        """Test logout endpoint is accessible."""
        response = client.get("/auth/logout")
        
        assert response.status_code == 200

    def test_logout_returns_json(self, client):
        """Test logout returns JSON response."""
        response = client.get("/auth/logout")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "logged_out"

    def test_github_callback_without_code_fails(self, client):
        """Test GitHub callback without code parameter fails."""
        with patch("api.auth.GITHUB_CLIENT_ID", "test_id"):
            with patch("api.auth.GITHUB_CLIENT_SECRET", "test_secret"):
                response = client.get("/auth/github/callback")
                
                assert response.status_code == 422

    def test_github_callback_without_credentials_fails(self, client):
        """Test GitHub callback without credentials fails."""
        with patch("api.auth.GITHUB_CLIENT_ID", ""):
            with patch("api.auth.GITHUB_CLIENT_SECRET", ""):
                response = client.get("/auth/github/callback?code=test_code")
                
                assert response.status_code == 500

    def test_auth_endpoints_use_correct_prefix(self, client):
        """Test auth endpoints use /auth prefix."""
        routes = [route.path for route in client.app.routes]
        auth_routes = [r for r in routes if r.startswith("/auth")]
        
        assert len(auth_routes) > 0
        assert "/auth/login" in auth_routes
        assert "/auth/logout" in auth_routes
        assert "/auth/github/callback" in auth_routes
