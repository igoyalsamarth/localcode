"""
Normalized payloads from GitHub webhooks for PR review agent.

`PROpenedForReview` is the contract between the `pull_request` webhook and the review agent.
"""

from typing import Any

from pydantic import BaseModel, Field


class PROpenedForReview(BaseModel):
    """
    Normalized `pull_request` event payload for the GitHub review agent.

    Used for both auto mode (``opened`` / ``synchronize``) and tag mode
    (``labeled`` with ``greagent:review``). Trigger selection is implemented in
    ``services.github.review_trigger``.
    """

    owner: str = Field(..., description="Repository owner login (user or org)")
    repo_name: str = Field(..., description="Short repository name")
    full_name: str = Field(..., description="owner/repo")
    repo_url: str = Field(..., description="HTTPS clone/browse URL")
    github_repo_id: int = Field(..., description="repository.id from the webhook")
    pr_number: int
    pr_title: str
    pr_body: str = ""
    base_branch: str = Field(..., description="Base branch (e.g. main)")
    head_branch: str = Field(..., description="Head branch (e.g. feature-branch)")
    head_sha: str = Field(..., description="Head commit SHA")
    base_sha: str | None = Field(
        default=None,
        description="Base commit SHA of the PR (from pull_request.base.sha); used to recover patches when the files API omits them.",
    )
    github_installation_id: int | None = Field(
        default=None,
        description="installation.id from the webhook (preferred when minting app tokens)",
    )
    github_sender_login: str | None = Field(
        default=None,
        description="sender.login from the webhook (for usage attribution)",
    )

    @classmethod
    def from_github_pr_event(cls, data: dict[str, Any]) -> "PROpenedForReview | None":
        """Parse owner, repo, and PR fields from a ``pull_request`` webhook body."""
        pr = data.get("pull_request") or {}
        repo = data.get("repository") or {}

        owner = (repo.get("owner") or {}).get("login")
        repo_name = repo.get("name")
        full_name = repo.get("full_name")
        pr_number = pr.get("number")
        pr_title = pr.get("title")

        if not owner or not repo_name or pr_number is None or pr_title is None:
            return None

        raw_repo_id = repo.get("id")
        try:
            github_repo_id = int(raw_repo_id) if raw_repo_id is not None else None
        except (TypeError, ValueError):
            github_repo_id = None
        if github_repo_id is None:
            return None

        if not full_name:
            full_name = f"{owner}/{repo_name}"

        body = pr.get("body")
        pr_body = body if isinstance(body, str) else ""

        base = pr.get("base") or {}
        head = pr.get("head") or {}
        base_branch = base.get("ref")
        head_branch = head.get("ref")
        head_sha = head.get("sha")
        base_sha_raw = base.get("sha")
        base_sha = str(base_sha_raw) if isinstance(base_sha_raw, str) else None

        if not base_branch or not head_branch or not head_sha:
            return None

        raw_inst = (data.get("installation") or {}).get("id")
        github_installation_id: int | None
        try:
            github_installation_id = int(raw_inst) if raw_inst is not None else None
        except (TypeError, ValueError):
            github_installation_id = None

        snd = data.get("sender") or {}
        sender_login = snd.get("login") if isinstance(snd.get("login"), str) else None

        return cls(
            owner=owner,
            repo_name=repo_name,
            full_name=full_name,
            repo_url=f"https://github.com/{full_name}",
            github_repo_id=github_repo_id,
            pr_number=int(pr_number),
            pr_title=str(pr_title),
            pr_body=pr_body,
            base_branch=str(base_branch),
            head_branch=str(head_branch),
            head_sha=str(head_sha),
            base_sha=base_sha,
            github_installation_id=github_installation_id,
            github_sender_login=sender_login,
        )
