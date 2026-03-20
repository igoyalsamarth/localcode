"""
Normalized payloads from GitHub webhooks for downstream agents.

`IssueOpenedForCoder` is the contract between the `issues` webhook and the coder agent.
"""

from typing import Any

from pydantic import BaseModel, Field

from services.github.coder_labels import CODE as CODER_LABEL_QUEUE


class IssueOpenedForCoder(BaseModel):
    """
    Normalized `issues` event payload for the GitHub coder agent.

    Triggered when someone applies ``greagent:code`` to an existing issue
    (``labeled``). Create the issue first, then add the label to start the coder.
    """

    owner: str = Field(..., description="Repository owner login (user or org)")
    repo_name: str = Field(..., description="Short repository name")
    full_name: str = Field(..., description="owner/repo")
    repo_url: str = Field(..., description="HTTPS clone/browse URL")
    issue_number: int
    issue_title: str
    issue_body: str = ""

    @classmethod
    def from_issues_webhook(cls, data: dict[str, Any]) -> "IssueOpenedForCoder | None":
        """
        Parse an `issues` webhook JSON body.

        Returns a work item only for ``labeled`` when the label applied is
        ``greagent:code`` (issue must already exist).

        Returns None for all other actions (including ``opened``, ``edited``, etc.).
        """
        if data.get("action") != "labeled":
            return None

        label_name = (data.get("label") or {}).get("name")
        if not isinstance(label_name, str) or label_name.strip() != CODER_LABEL_QUEUE:
            return None

        issue = data.get("issue") or {}
        repo = data.get("repository") or {}

        owner = (repo.get("owner") or {}).get("login")
        repo_name = repo.get("name")
        full_name = repo.get("full_name")
        issue_number = issue.get("number")
        issue_title = issue.get("title")

        if not owner or not repo_name or issue_number is None or issue_title is None:
            return None

        if not full_name:
            full_name = f"{owner}/{repo_name}"

        body = issue.get("body")
        issue_body = body if isinstance(body, str) else ""

        return cls(
            owner=owner,
            repo_name=repo_name,
            full_name=full_name,
            repo_url=f"https://github.com/{full_name}",
            issue_number=int(issue_number),
            issue_title=str(issue_title),
            issue_body=issue_body,
        )
