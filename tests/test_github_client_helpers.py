"""Tests for GitHub client helper functions."""

import pytest
from unittest.mock import patch

from services.github.client import _issue_headers


@pytest.mark.unit
class TestGitHubClientHelpers:
    """Test GitHub client helper functions."""

    def test_issue_headers_structure(self):
        """Test _issue_headers returns correct header structure."""
        token = "test_token_123"
        
        headers = _issue_headers(token)
        
        assert "Authorization" in headers
        assert "Accept" in headers
        assert "Content-Type" in headers
        assert "X-GitHub-Api-Version" in headers

    def test_issue_headers_authorization_format(self):
        """Test _issue_headers formats authorization correctly."""
        token = "ghp_test123"
        
        headers = _issue_headers(token)
        
        assert headers["Authorization"] == f"Bearer {token}"

    def test_issue_headers_accept_format(self):
        """Test _issue_headers sets correct Accept header."""
        token = "test_token"
        
        headers = _issue_headers(token)
        
        assert headers["Accept"] == "application/vnd.github+json"

    def test_issue_headers_content_type(self):
        """Test _issue_headers sets correct Content-Type."""
        token = "test_token"
        
        headers = _issue_headers(token)
        
        assert headers["Content-Type"] == "application/json"

    def test_issue_headers_with_empty_token(self):
        """Test _issue_headers with empty token."""
        token = ""
        
        headers = _issue_headers(token)
        
        assert headers["Authorization"] == "Bearer "

    def test_issue_headers_with_special_characters(self):
        """Test _issue_headers with special characters in token."""
        token = "token_with-special.chars_123"
        
        headers = _issue_headers(token)
        
        assert headers["Authorization"] == f"Bearer {token}"

    def test_issue_headers_api_version(self):
        """Test _issue_headers includes API version."""
        from constants import GITHUB_REST_API_VERSION
        token = "test_token"
        
        headers = _issue_headers(token)
        
        assert headers["X-GitHub-Api-Version"] == GITHUB_REST_API_VERSION

    def test_issue_headers_returns_dict(self):
        """Test _issue_headers returns a dictionary."""
        token = "test_token"
        
        headers = _issue_headers(token)
        
        assert isinstance(headers, dict)
        assert len(headers) == 4
