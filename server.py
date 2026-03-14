"""
FastAPI server to receive GitHub webhooks.

When an issue is created in a configured repository, the webhook is received
and can trigger downstream processing (e.g., the agent).
"""

import hashlib
import hmac
import json
import logging
import os
import uvicorn
from typing import Any
from constants import token
from github import add_issue_reaction

from fastapi import FastAPI, Header, HTTPException, Request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="LocalCode Webhook Server",
    description="Receives GitHub webhooks and triggers the agent on new issues",
    version="0.1.0",
)

WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")


def _verify_signature(payload: bytes, signature: str | None) -> bool:
    """Verify the GitHub webhook signature using HMAC-SHA256."""
    if not WEBHOOK_SECRET:
        logger.warning(
            "GITHUB_WEBHOOK_SECRET not set - skipping signature verification"
        )
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
):
    """
    Receive GitHub webhooks.

    Expects X-GitHub-Event: "issues" with action "opened" for new issue creation.
    """
    payload = await request.body()

    # Verify signature if secret is configured
    if not _verify_signature(payload, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Only process "issues" events
    if x_github_event != "issues":
        logger.info(f"Ignoring event type: {x_github_event}")
        return {"status": "ignored", "event": x_github_event}

    data: dict[str, Any] = json.loads(payload)
    action = data.get("action")

    # Only process new issue creation
    if action != "opened":
        logger.info(f"Ignoring issues action: {action}")
        return {"status": "ignored", "action": action}

    issue = data.get("issue", {})
    repo = data.get("repository", {})

    add_issue_reaction(
        owner=repo.get("owner", {}).get("login"),
        repo=repo.get("name"),
        issue_number=issue.get("number"),
        token=token,
        reaction="eyes",
    )

    logger.info(
        "Issue created: #%s %s in %s (delivery: %s)",
        issue.get("number"),
        issue.get("title"),
        repo.get("full_name"),
    )

    return {
        "status": "received",
        "issue_number": issue.get("number"),
        "issue_title": issue.get("title"),
        "issue_description": issue.get("body"),
        "repository": repo.get("url"),
    }


def run() -> None:
    """Run the webhook server. Use: uv run serve or python -m server"""

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    run()
