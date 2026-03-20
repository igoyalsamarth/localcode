"""GitHub webhook HMAC-SHA256 signature verification."""

import hashlib
import hmac

from constants import GITHUB_WEBHOOK_SECRET
from logger import get_logger

logger = get_logger(__name__)


def verify_github_webhook_signature(payload: bytes, signature: str | None) -> bool:
    """Verify the GitHub webhook signature using HMAC-SHA256."""
    if not GITHUB_WEBHOOK_SECRET:
        logger.warning(
            "GITHUB_WEBHOOK_SECRET not set - skipping signature verification"
        )
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
