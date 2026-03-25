"""Tests for onboarding validation logic."""

import pytest
from pydantic import ValidationError

from model.schemas import OnboardingRequest


@pytest.mark.unit
class TestOnboardingValidation:
    """Test onboarding request validation."""

    def test_onboarding_request_valid_full(self):
        """Test valid onboarding request with all fields."""
        data = {
            "organization": "Test Org",
            "username": "testuser",
            "fullName": "Test User",
            "bio": "This is a test bio",
        }
        
        request = OnboardingRequest(**data)
        
        assert request.organization == "Test Org"
        assert request.username == "testuser"
        assert request.fullName == "Test User"
        assert request.bio == "This is a test bio"

    def test_onboarding_request_valid_minimal(self):
        """Test valid onboarding request with minimal fields."""
        data = {
            "organization": "Test Org",
            "username": "testuser",
        }
        
        request = OnboardingRequest(**data)
        
        assert request.organization == "Test Org"
        assert request.username == "testuser"
        assert request.fullName is None
        assert request.bio is None

    def test_onboarding_request_missing_organization(self):
        """Test onboarding request with missing organization."""
        data = {
            "username": "testuser",
        }
        
        with pytest.raises(ValidationError):
            OnboardingRequest(**data)

    def test_onboarding_request_missing_username(self):
        """Test onboarding request with missing username."""
        data = {
            "organization": "Test Org",
        }
        
        with pytest.raises(ValidationError):
            OnboardingRequest(**data)

    def test_onboarding_request_empty_organization(self):
        """Test onboarding request with empty organization."""
        data = {
            "organization": "",
            "username": "testuser",
        }
        
        request = OnboardingRequest(**data)
        assert request.organization == ""

    def test_onboarding_request_empty_username(self):
        """Test onboarding request with empty username."""
        data = {
            "organization": "Test Org",
            "username": "",
        }
        
        request = OnboardingRequest(**data)
        assert request.username == ""

    def test_onboarding_request_long_bio(self):
        """Test onboarding request with long bio."""
        data = {
            "organization": "Test Org",
            "username": "testuser",
            "bio": "x" * 200,
        }
        
        request = OnboardingRequest(**data)
        assert len(request.bio) == 200

    def test_onboarding_request_special_characters_in_username(self):
        """Test onboarding request with special characters in username."""
        data = {
            "organization": "Test Org",
            "username": "test-user_123",
        }
        
        request = OnboardingRequest(**data)
        assert request.username == "test-user_123"

    def test_onboarding_request_unicode_in_fields(self):
        """Test onboarding request with unicode characters."""
        data = {
            "organization": "Test Org 🚀",
            "username": "testuser",
            "fullName": "Test User 👨‍💻",
            "bio": "Bio with emoji 🎉",
        }
        
        request = OnboardingRequest(**data)
        assert "🚀" in request.organization
        assert "👨‍💻" in request.fullName
        assert "🎉" in request.bio

    def test_onboarding_request_whitespace_handling(self):
        """Test onboarding request with whitespace."""
        data = {
            "organization": "  Test Org  ",
            "username": "  testuser  ",
            "fullName": "  Test User  ",
        }
        
        request = OnboardingRequest(**data)
        assert request.organization == "  Test Org  "
        assert request.username == "  testuser  "
        assert request.fullName == "  Test User  "

    def test_onboarding_request_none_optional_fields(self):
        """Test onboarding request with explicitly None optional fields."""
        data = {
            "organization": "Test Org",
            "username": "testuser",
            "fullName": None,
            "bio": None,
        }
        
        request = OnboardingRequest(**data)
        assert request.fullName is None
        assert request.bio is None
