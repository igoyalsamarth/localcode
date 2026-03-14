"""
FastAPI server to receive GitHub webhooks.

When an issue is created in a configured repository, the webhook is received
and triggers the agent to implement changes, open a PR, and comment on the issue.
"""

import hashlib
import hmac
import json
import logging
import os
import uvicorn
from typing import Any
from constants import token
from github import (
    add_issue_reaction,
    comment_on_issue,
    create_pull_request,
    get_default_branch,
)
from agent import run_agent_on_issue

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

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
    background_tasks: BackgroundTasks,
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

    # Run agent in background (returns quickly to GitHub)
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

        base = get_default_branch(owner, repo_name, token)
        branch_name = f"agent/issue-{issue_number}"
        pr_body = f"Fixes #{issue_number}\n\n{issue_title}\n\n{issue_body or ''}"
        pr = create_pull_request(
            owner=owner,
            repo=repo_name,
            token=token,
            title=issue_title,
            body=pr_body,
            head=branch_name,
            base=base,
        )
        pr_url = pr.get("html_url", "")
        comment_on_issue(
            owner=owner,
            repo=repo_name,
            issue_number=issue_number,
            token=token,
            body=f"I've created a PR to address this issue: {pr_url}",
        )
        logger.info("PR created for issue #%s: %s", issue_number, pr_url)
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


def run() -> None:
    """Run the webhook server. Use: uv run serve or python -m server"""

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    run()
