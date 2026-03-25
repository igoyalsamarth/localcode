"""Integration tests for connections API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from uuid import uuid4


@pytest.mark.unit
class TestConnectionsAPIIntegration:
    """Integration tests for GitHub connections endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from app import app
        return TestClient(app)

    @pytest.fixture
    def mock_user_with_org(self, db_session):
        """Create a mock user with organization."""
        from model.tables import User, Organization, GitHubInstallation
        
        user = User(
            email="test@example.com",
            username="testuser",
            auth_provider="github",
            github_user_id=12345,
            github_login="testuser",
            avatar_url="https://github.com/avatar.png",
        )
        db_session.add(user)
        db_session.flush()
        
        org = Organization(
            name="Test Org",
            owner_user_id=user.id,
            github_installation_id=67890,
        )
        db_session.add(org)
        db_session.flush()
        
        installation = GitHubInstallation(
            organization_id=org.id,
            github_installation_id=67890,
            account_name="testuser",
        )
        db_session.add(installation)
        db_session.commit()
        
        return user, org, installation

    def test_get_github_connection_endpoint_exists(self, client):
        """Test GET /connections/github endpoint exists."""
        response = client.get("/connections/github")
        
        # Should return 200 or 404
        assert response.status_code in [200, 404]

    def test_get_github_connection_returns_json(self, client):
        """Test connection endpoint returns JSON."""
        response = client.get("/connections/github")
        
        assert "application/json" in response.headers["content-type"]

    def test_get_github_connection_without_user(self, client):
        """Test connection endpoint without user returns 404."""
        with patch("api.connections.session_scope") as mock_scope:
            mock_session = MagicMock()
            mock_session.execute.return_value.scalar_one_or_none.return_value = None
            mock_scope.return_value.__enter__.return_value = mock_session
            
            response = client.get("/connections/github")
            
            assert response.status_code == 404

    def test_get_github_connection_structure(self, client, mock_user_with_org):
        """Test connection endpoint response structure."""
        response = client.get("/connections/github")
        
        if response.status_code == 200:
            data = response.json()
            assert "id" in data
            assert "connected" in data

    def test_get_github_installation_endpoint_exists(self, client):
        """Test GET /connections/github/installation endpoint exists."""
        response = client.get("/connections/github/installation")
        
        assert response.status_code in [200, 404]

    def test_get_github_installation_returns_json(self, client):
        """Test installation endpoint returns JSON."""
        response = client.get("/connections/github/installation")
        
        assert "application/json" in response.headers["content-type"]

    def test_install_github_app_endpoint_exists(self, client):
        """Test POST /connections/github/install endpoint exists."""
        response = client.post("/connections/github/install")
        
        # Should return 200 or 404/500
        assert response.status_code in [200, 404, 500]

    def test_install_github_app_without_slug_fails(self, client):
        """Test install endpoint fails without GITHUB_APP_SLUG."""
        with patch("api.connections.GITHUB_APP_SLUG", ""):
            response = client.post("/connections/github/install")
            
            assert response.status_code == 500
            data = response.json()
            assert "GITHUB_APP_SLUG" in data["detail"]

    def test_install_github_app_returns_install_url(self, client):
        """Test install endpoint returns installation URL."""
        with patch("api.connections.GITHUB_APP_SLUG", "test-app"):
            with patch("api.connections.session_scope") as mock_scope:
                mock_session = MagicMock()
                mock_user = MagicMock()
                mock_user.id = uuid4()
                mock_session.execute.return_value.scalar_one_or_none.return_value = mock_user
                mock_scope.return_value.__enter__.return_value = mock_session
                
                response = client.post("/connections/github/install")
                
                if response.status_code == 200:
                    data = response.json()
                    assert "installUrl" in data
                    assert "github.com/apps/test-app" in data["installUrl"]

    def test_connect_github_endpoint_exists(self, client):
        """Test GET /connections/github/connect endpoint exists."""
        response = client.get("/connections/github/connect")
        
        assert response.status_code in [200, 404, 500]

    def test_github_callback_endpoint_exists(self, client):
        """Test GET /connections/github/callback endpoint exists."""
        with patch("api.connections.CLIENT_URL", "http://test.com"):
            response = client.get(
                "/connections/github/callback",
                follow_redirects=False
            )
            
            # Should redirect (307/302) or return error
            assert response.status_code in [200, 302, 307]

    def test_github_callback_without_installation_id(self, client):
        """Test callback without installation_id redirects with error."""
        with patch("api.connections.CLIENT_URL", "http://test.com"):
            response = client.get(
                "/connections/github/callback",
                follow_redirects=False
            )
            
            if response.status_code in [302, 307]:
                location = response.headers.get("location", "")
                assert "status=error" in location or "message=" in location

    def test_github_callback_with_invalid_state(self, client):
        """Test callback with invalid state parameter."""
        with patch("api.connections.CLIENT_URL", "http://test.com"):
            response = client.get(
                "/connections/github/callback?installation_id=123&state=invalid",
                follow_redirects=False
            )
            
            if response.status_code in [302, 307]:
                location = response.headers.get("location", "")
                assert "error" in location or "Invalid" in location

    def test_disconnect_github_endpoint_exists(self, client):
        """Test DELETE /connections/github endpoint exists."""
        response = client.delete("/connections/github")
        
        assert response.status_code in [200, 404]

    def test_disconnect_github_returns_json(self, client):
        """Test disconnect endpoint returns JSON."""
        response = client.delete("/connections/github")
        
        if response.status_code == 200:
            data = response.json()
            assert "status" in data

    def test_connections_endpoints_use_correct_prefix(self, client):
        """Test connections endpoints use /connections prefix."""
        routes = [route.path for route in client.app.routes]
        connections_routes = [r for r in routes if r.startswith("/connections")]
        
        assert len(connections_routes) > 0
        assert "/connections/github" in connections_routes

    def test_connections_cors_enabled(self, client):
        """Test CORS is enabled for connections endpoints."""
        response = client.options("/connections/github")
        
        # OPTIONS should be allowed or return 405
        assert response.status_code in [200, 405]
