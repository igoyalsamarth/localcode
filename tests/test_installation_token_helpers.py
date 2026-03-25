"""Tests for installation token helper functions."""

import pytest
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from services.github.installation_token import (
    _private_key_pem,
    app_credentials_configured,
    _jwt_iss_claim,
    _parse_expires_at,
)


@pytest.mark.unit
class TestInstallationTokenHelpers:
    """Test installation token helper functions."""

    def test_private_key_pem_replaces_escaped_newlines(self):
        """Test _private_key_pem replaces \\n with actual newlines."""
        test_key = "-----BEGIN RSA PRIVATE KEY-----\\nline1\\nline2\\n-----END RSA PRIVATE KEY-----"
        
        with patch("services.github.installation_token.GITHUB_APP_PRIVATE_KEY", test_key):
            result = _private_key_pem()
            
            assert "\\n" not in result
            assert "\n" in result
            assert result.count("\n") == 3

    def test_private_key_pem_handles_empty_key(self):
        """Test _private_key_pem handles empty key."""
        with patch("services.github.installation_token.GITHUB_APP_PRIVATE_KEY", ""):
            result = _private_key_pem()
            
            assert result == ""

    def test_private_key_pem_handles_none(self):
        """Test _private_key_pem handles None."""
        with patch("services.github.installation_token.GITHUB_APP_PRIVATE_KEY", None):
            result = _private_key_pem()
            
            assert result == ""

    def test_private_key_pem_no_escaped_newlines(self):
        """Test _private_key_pem with no escaped newlines."""
        test_key = "-----BEGIN RSA PRIVATE KEY-----\nline1\nline2\n-----END RSA PRIVATE KEY-----"
        
        with patch("services.github.installation_token.GITHUB_APP_PRIVATE_KEY", test_key):
            result = _private_key_pem()
            
            assert result == test_key

    def test_app_credentials_configured_with_client_id_and_key(self):
        """Test app_credentials_configured returns True with client ID and key."""
        with patch("services.github.installation_token.GITHUB_APP_PRIVATE_KEY", "test_key"):
            with patch("services.github.installation_token.GITHUB_APP_CLIENT_ID", "test_client_id"):
                with patch("services.github.installation_token.GITHUB_APP_ID", ""):
                    result = app_credentials_configured()
                    
                    assert result is True

    def test_app_credentials_configured_with_app_id_and_key(self):
        """Test app_credentials_configured returns True with app ID and key."""
        with patch("services.github.installation_token.GITHUB_APP_PRIVATE_KEY", "test_key"):
            with patch("services.github.installation_token.GITHUB_APP_CLIENT_ID", ""):
                with patch("services.github.installation_token.GITHUB_APP_ID", "12345"):
                    result = app_credentials_configured()
                    
                    assert result is True

    def test_app_credentials_configured_missing_key(self):
        """Test app_credentials_configured returns False without key."""
        with patch("services.github.installation_token.GITHUB_APP_PRIVATE_KEY", ""):
            with patch("services.github.installation_token.GITHUB_APP_CLIENT_ID", "test_client_id"):
                result = app_credentials_configured()
                
                assert result is False

    def test_app_credentials_configured_missing_issuer(self):
        """Test app_credentials_configured returns False without issuer."""
        with patch("services.github.installation_token.GITHUB_APP_PRIVATE_KEY", "test_key"):
            with patch("services.github.installation_token.GITHUB_APP_CLIENT_ID", ""):
                with patch("services.github.installation_token.GITHUB_APP_ID", ""):
                    result = app_credentials_configured()
                    
                    assert result is False

    def test_app_credentials_configured_all_missing(self):
        """Test app_credentials_configured returns False when all missing."""
        with patch("services.github.installation_token.GITHUB_APP_PRIVATE_KEY", ""):
            with patch("services.github.installation_token.GITHUB_APP_CLIENT_ID", ""):
                with patch("services.github.installation_token.GITHUB_APP_ID", ""):
                    result = app_credentials_configured()
                    
                    assert result is False

    def test_jwt_iss_claim_returns_client_id(self):
        """Test _jwt_iss_claim returns client ID when available."""
        with patch("services.github.installation_token.GITHUB_APP_CLIENT_ID", "  Iv1.test123  "):
            with patch("services.github.installation_token.GITHUB_APP_ID", "12345"):
                result = _jwt_iss_claim()
                
                assert result == "Iv1.test123"
                assert isinstance(result, str)

    def test_jwt_iss_claim_returns_app_id_when_no_client_id(self):
        """Test _jwt_iss_claim returns app ID when client ID is empty."""
        with patch("services.github.installation_token.GITHUB_APP_CLIENT_ID", "  "):
            with patch("services.github.installation_token.GITHUB_APP_ID", "  12345  "):
                result = _jwt_iss_claim()
                
                assert result == 12345
                assert isinstance(result, int)

    def test_jwt_iss_claim_raises_when_both_missing(self):
        """Test _jwt_iss_claim raises when both IDs are missing."""
        with patch("services.github.installation_token.GITHUB_APP_CLIENT_ID", ""):
            with patch("services.github.installation_token.GITHUB_APP_ID", ""):
                with pytest.raises(RuntimeError, match="Set GITHUB_APP_CLIENT_ID"):
                    _jwt_iss_claim()

    def test_parse_expires_at_with_z_suffix(self):
        """Test _parse_expires_at parses ISO timestamp with Z suffix."""
        timestamp = "2024-03-25T12:00:00Z"
        
        result = _parse_expires_at(timestamp)
        
        assert isinstance(result, float)
        assert result > 0

    def test_parse_expires_at_with_timezone(self):
        """Test _parse_expires_at parses ISO timestamp with timezone."""
        timestamp = "2024-03-25T12:00:00+00:00"
        
        result = _parse_expires_at(timestamp)
        
        assert isinstance(result, float)
        assert result > 0

    def test_parse_expires_at_converts_z_to_timezone(self):
        """Test _parse_expires_at converts Z to +00:00."""
        timestamp_z = "2024-03-25T12:00:00Z"
        timestamp_tz = "2024-03-25T12:00:00+00:00"
        
        result_z = _parse_expires_at(timestamp_z)
        result_tz = _parse_expires_at(timestamp_tz)
        
        assert result_z == result_tz

    def test_parse_expires_at_returns_unix_timestamp(self):
        """Test _parse_expires_at returns Unix timestamp."""
        timestamp = "2024-01-01T00:00:00Z"
        
        result = _parse_expires_at(timestamp)
        
        expected = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()
        assert result == expected

    def test_parse_expires_at_handles_microseconds(self):
        """Test _parse_expires_at handles microseconds."""
        timestamp = "2024-03-25T12:00:00.123456Z"
        
        result = _parse_expires_at(timestamp)
        
        assert isinstance(result, float)
        assert result > 0

    def test_parse_expires_at_adds_utc_timezone_if_missing(self):
        """Test _parse_expires_at adds UTC timezone if missing."""
        timestamp = "2024-03-25T12:00:00"
        
        result = _parse_expires_at(timestamp)
        
        expected = datetime(2024, 3, 25, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        assert result == expected
