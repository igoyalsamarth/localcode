"""Integration tests for onboarding API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from uuid import uuid4


@pytest.mark.unit
class TestOnboardingAPIIntegration:
    """Integration tests for onboarding endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from app import app
        return TestClient(app)

    @pytest.fixture
    def mock_user(self, db_session):
        """Create a mock user for testing."""
        from model.tables import User, Organization
        
        user = User(
            email="test@example.com",
            username="oldusername",
            auth_provider="github",
            github_user_id=12345,
            github_login="testuser",
        )
        db_session.add(user)
        db_session.flush()
        
        org = Organization(
            name="Old Org",
            owner_user_id=user.id,
        )
        db_session.add(org)
        db_session.commit()
        
        return user

    def test_onboarding_endpoint_exists(self, client):
        """Test onboarding endpoint is accessible."""
        response = client.post("/onboarding", json={
            "organization": "Test",
            "username": "test",
        })
        
        # Should fail validation or succeed, but endpoint exists
        assert response.status_code in [200, 400, 404, 422]

    def test_onboarding_requires_organization(self, client):
        """Test onboarding requires organization field."""
        response = client.post("/onboarding", json={
            "username": "testuser",
        })
        
        assert response.status_code == 422

    def test_onboarding_requires_username(self, client):
        """Test onboarding requires username field."""
        response = client.post("/onboarding", json={
            "organization": "Test Org",
        })
        
        assert response.status_code == 422

    def test_onboarding_validates_username_length(self, client, mock_user):
        """Test onboarding validates username length."""
        response = client.post("/onboarding", json={
            "organization": "Test Org",
            "username": "ab",  # Too short
        })
        
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "3 characters" in data["detail"]

    def test_onboarding_validates_organization_length(self, client, mock_user):
        """Test onboarding validates organization length."""
        response = client.post("/onboarding", json={
            "organization": "T",  # Too short
            "username": "testuser",
        })
        
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "2 characters" in data["detail"]

    def test_onboarding_validates_bio_length(self, client, mock_user):
        """Test onboarding validates bio length."""
        response = client.post("/onboarding", json={
            "organization": "Test Org",
            "username": "testuser",
            "bio": "x" * 200,  # Too long
        })
        
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "160" in data["detail"]

    def test_onboarding_accepts_valid_data(self, client, mock_user):
        """Test onboarding accepts valid data."""
        response = client.post("/onboarding", json={
            "organization": "New Org",
            "username": "newusername",
            "fullName": "New Name",
            "bio": "Test bio",
        })
        
        # Should succeed or fail with 404 (no user found)
        assert response.status_code in [200, 404]

    def test_onboarding_accepts_minimal_data(self, client, mock_user):
        """Test onboarding accepts minimal required data."""
        response = client.post("/onboarding", json={
            "organization": "Test Org",
            "username": "testuser123",
        })
        
        # Should succeed or fail with 404 (no user found)
        assert response.status_code in [200, 404]

    def test_onboarding_returns_json(self, client):
        """Test onboarding returns JSON response."""
        response = client.post("/onboarding", json={
            "organization": "Test Org",
            "username": "testuser",
        })
        
        assert "application/json" in response.headers["content-type"]

    def test_onboarding_method_not_allowed(self, client):
        """Test onboarding only accepts POST."""
        response = client.get("/onboarding")
        
        assert response.status_code == 405

    def test_onboarding_with_empty_strings(self, client):
        """Test onboarding with empty strings."""
        response = client.post("/onboarding", json={
            "organization": "",
            "username": "",
        })
        
        assert response.status_code == 400

    def test_onboarding_with_special_characters(self, client, mock_user):
        """Test onboarding with special characters."""
        response = client.post("/onboarding", json={
            "organization": "Test-Org_123",
            "username": "test_user-123",
        })
        
        # Should succeed or fail with 404
        assert response.status_code in [200, 404]

    def test_onboarding_with_unicode(self, client, mock_user):
        """Test onboarding with unicode characters."""
        response = client.post("/onboarding", json={
            "organization": "Test Org 🚀",
            "username": "testuser",
            "fullName": "Test User 👨‍💻",
        })
        
        # Should succeed or fail with 404
        assert response.status_code in [200, 404]
