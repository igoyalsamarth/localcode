"""Tests for health check API endpoint."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import app
from db.client import Base


@pytest.fixture
def test_client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.mark.unit
class TestHealthAPI:
    """Test health check endpoint."""

    def test_health_check_success(self, test_client):
        """Test health check returns OK when database is connected."""
        with patch("api.health.get_engine") as mock_get_engine:
            mock_engine = MagicMock()
            mock_conn = MagicMock()
            mock_engine.connect.return_value.__enter__.return_value = mock_conn
            mock_get_engine.return_value = mock_engine
            
            response = test_client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["database"] == "connected"

    def test_health_check_database_error(self, test_client):
        """Test health check returns 503 when database is disconnected."""
        with patch("api.health.get_engine") as mock_get_engine:
            mock_engine = MagicMock()
            mock_engine.connect.side_effect = Exception("Database connection failed")
            mock_get_engine.return_value = mock_engine
            
            response = test_client.get("/health")
            
            assert response.status_code == 503
            data = response.json()
            assert "detail" in data
            assert data["detail"]["status"] == "unhealthy"
            assert data["detail"]["database"] == "disconnected"
            assert "error" in data["detail"]

    def test_health_check_executes_query(self, test_client):
        """Test health check executes a test query."""
        with patch("api.health.get_engine") as mock_get_engine:
            mock_engine = MagicMock()
            mock_conn = MagicMock()
            mock_engine.connect.return_value.__enter__.return_value = mock_conn
            mock_get_engine.return_value = mock_engine
            
            response = test_client.get("/health")
            
            assert response.status_code == 200
            mock_conn.execute.assert_called_once()
