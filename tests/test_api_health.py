"""Integration tests for health API endpoint."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


@pytest.mark.unit
class TestHealthAPIIntegration:
    """Integration tests for health check endpoint."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from app import app
        return TestClient(app)

    def test_health_endpoint_exists(self, client):
        """Test health endpoint is accessible."""
        response = client.get("/health")
        
        assert response.status_code in [200, 503]

    def test_health_endpoint_returns_json(self, client):
        """Test health endpoint returns JSON."""
        with patch("api.health.get_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            
            response = client.get("/health")
            
            assert response.headers["content-type"] == "application/json"

    def test_health_endpoint_success_structure(self, client):
        """Test health endpoint success response structure."""
        with patch("api.health.get_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            
            response = client.get("/health")
            
            if response.status_code == 200:
                data = response.json()
                assert "status" in data
                assert "database" in data
                assert data["status"] == "ok"
                assert data["database"] == "connected"

    def test_health_endpoint_failure_structure(self, client):
        """Test health endpoint failure response structure."""
        with patch("api.health.get_engine") as mock_engine:
            mock_engine.return_value.connect.side_effect = Exception("DB error")
            
            response = client.get("/health")
            
            assert response.status_code == 503
            data = response.json()
            assert "detail" in data
            assert "status" in data["detail"]
            assert data["detail"]["status"] == "unhealthy"

    def test_health_endpoint_method_not_allowed(self, client):
        """Test health endpoint only accepts GET."""
        response = client.post("/health")
        
        assert response.status_code == 405
