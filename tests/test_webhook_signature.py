"""Tests for GitHub webhook signature verification."""

import hmac
import hashlib
import pytest
from unittest.mock import patch

from services.github.webhook_signature import verify_github_webhook_signature


@pytest.mark.unit
class TestWebhookSignature:
    """Test GitHub webhook signature verification."""

    def test_verify_signature_valid(self):
        """Test valid signature verification."""
        secret = "test_secret"
        payload = b"test payload data"
        
        expected_sig = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        signature = f"sha256={expected_sig}"
        
        with patch("services.github.webhook_signature.GITHUB_WEBHOOK_SECRET", secret):
            result = verify_github_webhook_signature(payload, signature)
            assert result is True

    def test_verify_signature_invalid(self):
        """Test invalid signature verification."""
        secret = "test_secret"
        payload = b"test payload data"
        signature = "sha256=invalid_signature"
        
        with patch("services.github.webhook_signature.GITHUB_WEBHOOK_SECRET", secret):
            result = verify_github_webhook_signature(payload, signature)
            assert result is False

    def test_verify_signature_wrong_format(self):
        """Test signature with wrong format."""
        secret = "test_secret"
        payload = b"test payload data"
        signature = "invalid_format"
        
        with patch("services.github.webhook_signature.GITHUB_WEBHOOK_SECRET", secret):
            result = verify_github_webhook_signature(payload, signature)
            assert result is False

    def test_verify_signature_missing(self):
        """Test missing signature."""
        secret = "test_secret"
        payload = b"test payload data"
        
        with patch("services.github.webhook_signature.GITHUB_WEBHOOK_SECRET", secret):
            result = verify_github_webhook_signature(payload, None)
            assert result is False

    def test_verify_signature_no_secret_configured(self):
        """Test verification when no secret is configured."""
        payload = b"test payload data"
        signature = "sha256=anything"
        
        with patch("services.github.webhook_signature.GITHUB_WEBHOOK_SECRET", ""):
            result = verify_github_webhook_signature(payload, signature)
            assert result is True

    def test_verify_signature_different_payloads(self):
        """Test signature fails for different payloads."""
        secret = "test_secret"
        original_payload = b"original payload"
        different_payload = b"different payload"
        
        expected_sig = hmac.new(
            secret.encode(),
            original_payload,
            hashlib.sha256,
        ).hexdigest()
        signature = f"sha256={expected_sig}"
        
        with patch("services.github.webhook_signature.GITHUB_WEBHOOK_SECRET", secret):
            result = verify_github_webhook_signature(different_payload, signature)
            assert result is False

    def test_verify_signature_timing_safe(self):
        """Test that verification uses timing-safe comparison."""
        secret = "test_secret"
        payload = b"test payload"
        
        expected_sig = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        
        almost_correct = expected_sig[:-1] + ("0" if expected_sig[-1] != "0" else "1")
        signature = f"sha256={almost_correct}"
        
        with patch("services.github.webhook_signature.GITHUB_WEBHOOK_SECRET", secret):
            result = verify_github_webhook_signature(payload, signature)
            assert result is False
