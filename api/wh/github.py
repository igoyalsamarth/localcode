"""GitHub webhook handler."""

import hashlib
import hmac
import json
import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from constants import token
from github import add_issue_reaction, comment_on_issue
from agent import run_agent_on_issue
from logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhooks"])

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


def _handle_issue_sync(
    owner: str,
    repo_name: str,
    full_name: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
) -> None:
    """Run agent, create PR, comment on issue. Runs in a thread."""
    try:
        run_agent_on_issue(
            repo_url=f"https://github.com/{full_name}",
            repo_name=repo_name,
            issue_number=issue_number,
            issue_title=issue_title,
            issue_body=issue_body,
        )

    except Exception as e:
        logger.exception("Failed to handle issue #%s: %s", issue_number, e)
        try:
            comment_on_issue(
                owner=owner,
                repo=repo_name,
                issue_number=issue_number,
                token=token,
                body=f"⚠️ Sorry, I encountered an error while working on this issue:\n\n```\n{e}\n```",
            )
        except Exception as comment_err:
            logger.exception("Failed to post error comment: %s", comment_err)


@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
):
    """
    Receive GitHub webhooks.

    Expects X-GitHub-Event: "issues" with action "opened" for new issue creation.
    """
    payload = await request.body()

    if not _verify_signature(payload, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    if x_github_event != "issues":
        logger.info(f"Ignoring event type: {x_github_event}")
        return {"status": "ignored", "event": x_github_event}

    data: dict[str, Any] = json.loads(payload)
    action = data.get("action")

    if action != "opened":
        logger.info(f"Ignoring issues action: {action}")
        return {"status": "ignored", "action": action}

    issue = data.get("issue", {})
    repo = data.get("repository", {})

    owner = repo.get("owner", {}).get("login")
    repo_name = repo.get("name")
    full_name = repo.get("full_name", f"{owner}/{repo_name}")
    issue_number = issue.get("number")
    issue_title = issue.get("title")
    issue_body = issue.get("body") or ""

    add_issue_reaction(
        owner=owner,
        repo=repo_name,
        issue_number=issue_number,
        token=token,
        reaction="eyes",
    )

    logger.info(
        "Issue created: #%s %s in %s",
        issue_number,
        issue_title,
        full_name,
    )

    background_tasks.add_task(
        _handle_issue_sync,
        owner=owner,
        repo_name=repo_name,
        full_name=full_name,
        issue_number=issue_number,
        issue_title=issue_title,
        issue_body=issue_body,
    )

    return {
        "status": "received",
        "issue_number": issue_number,
        "issue_title": issue_title,
        "repository": full_name,
    }
