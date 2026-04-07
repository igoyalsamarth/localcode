"""GitHub REST API helpers for issues (reactions, comments, labels)."""

from typing import Any

from urllib.parse import quote

import requests

from constants import GITHUB_REST_API_VERSION
from logger import get_logger


logger = get_logger(__name__)

_DEFAULT_REQUEST_TIMEOUT_SEC = 60
_MAX_LIST_PAGES = 25


def add_issue_reaction(
    owner: str, repo: str, issue_number: int, token: str, reaction: str = "eyes"
):
    """
    Add a reaction to a GitHub issue.

    Parameters
    ----------
    owner : str
        Repository owner
    repo : str
        Repository name
    issue_number : int
        Issue number
    token : str
        GitHub personal access token or GitHub App token
    reaction : str
        Reaction type (default: "eyes")

    Returns
    -------
    dict
        GitHub API response
    """

    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/reactions"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": GITHUB_REST_API_VERSION,
    }

    payload = {"content": reaction}

    logger.info(
        "Adding reaction '%s' to issue #%s in %s/%s",
        reaction,
        issue_number,
        owner,
        repo,
    )
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()

    return response.json()


def comment_on_issue(owner: str, repo: str, issue_number: int, token: str, body: str):
    """Add a comment to a GitHub issue."""

    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": GITHUB_REST_API_VERSION,
    }

    payload = {"body": body}

    r = requests.post(url, headers=headers, json=payload)
    r.raise_for_status()
    return r.json()


def _issue_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": GITHUB_REST_API_VERSION,
    }


def _get_json_paginated_list(
    url: str,
    token: str,
    *,
    max_pages: int = _MAX_LIST_PAGES,
) -> list[dict[str, Any]]:
    """GET a GitHub REST collection with ``page`` / ``per_page`` until exhausted or capped."""
    headers = _issue_headers(token)
    out: list[dict[str, Any]] = []
    page = 1
    per_page = 100
    while page <= max_pages:
        r = requests.get(
            url,
            headers=headers,
            params={"per_page": per_page, "page": page},
            timeout=_DEFAULT_REQUEST_TIMEOUT_SEC,
        )
        r.raise_for_status()
        batch = r.json()
        if not isinstance(batch, list) or not batch:
            break
        out.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return out


def list_pr_issue_comments(
    owner: str, repo: str, pr_number: int, token: str
) -> list[dict[str, Any]]:
    """
    List issue (conversation) comments on a pull request.

    Uses ``GET /repos/{owner}/{repo}/issues/{pr_number}/comments``.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
    return _get_json_paginated_list(url, token)


def list_pr_review_comments(
    owner: str, repo: str, pr_number: int, token: str
) -> list[dict[str, Any]]:
    """
    List inline review comments on a pull request.

    Uses ``GET /repos/{owner}/{repo}/pulls/{pr_number}/comments``.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/comments"
    return _get_json_paginated_list(url, token)


def list_pr_review_files(
    owner: str, repo: str, pr_number: int, token: str
) -> list[dict[str, Any]]:
    """
    List changed files on a pull request, including per-file patch hunks when available.

    Uses ``GET /repos/{owner}/{repo}/pulls/{pr_number}/files``.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
    return _get_json_paginated_list(url, token)


def ensure_repo_label_exists(
    owner: str,
    repo: str,
    token: str,
    name: str,
    color: str = "a37761",
) -> None:
    """
    Ensure a label exists on the repository.

    GitHub only lets you attach labels that already exist on the repo; this creates
    the label when missing (GET 404 → POST create).
    """
    enc = quote(name, safe="")
    get_url = f"https://api.github.com/repos/{owner}/{repo}/labels/{enc}"
    headers = _issue_headers(token)
    r = requests.get(get_url, headers=headers)
    if r.status_code == 200:
        return
    if r.status_code == 404:
        create_url = f"https://api.github.com/repos/{owner}/{repo}/labels"
        r2 = requests.post(
            create_url,
            headers=headers,
            json={"name": name, "color": color},
        )
        if r2.status_code in (201, 422):
            # 422: label already exists (race) or validation; issue attach will fail if still missing
            return
        r2.raise_for_status()
        return
    r.raise_for_status()


def remove_issue_label(
    owner: str, repo: str, issue_number: int, label_name: str, token: str
) -> None:
    """Remove a label from an issue. No-op if the label is not present (404)."""
    enc = quote(label_name, safe="")
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/labels/{enc}"
    r = requests.delete(url, headers=_issue_headers(token))
    if r.status_code == 404:
        return
    r.raise_for_status()


def add_issue_labels(
    owner: str, repo: str, issue_number: int, token: str, labels: list[str]
) -> list[dict]:
    """Add labels to an issue (additive; does not remove existing labels)."""
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/labels"
    r = requests.post(
        url,
        headers=_issue_headers(token),
        json={"labels": labels},
    )
    r.raise_for_status()
    return r.json()


def add_pr_labels(
    owner: str, repo: str, pr_number: int, token: str, labels: list[str]
) -> list[dict]:
    """Add labels to a PR (additive; does not remove existing labels)."""
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/labels"
    r = requests.post(
        url,
        headers=_issue_headers(token),
        json={"labels": labels},
    )
    r.raise_for_status()
    return r.json()


def remove_pr_label(
    owner: str, repo: str, pr_number: int, label_name: str, token: str
) -> None:
    """Remove a label from a PR. No-op if the label is not present (404)."""
    enc = quote(label_name, safe="")
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/labels/{enc}"
    r = requests.delete(url, headers=_issue_headers(token))
    if r.status_code == 404:
        return
    r.raise_for_status()


def comment_on_pr(owner: str, repo: str, pr_number: int, token: str, body: str):
    """Add a comment to a GitHub PR."""
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": GITHUB_REST_API_VERSION,
    }
    payload = {"body": body}
    r = requests.post(url, headers=headers, json=payload)
    r.raise_for_status()
    return r.json()


def approve_pr(owner: str, repo: str, pr_number: int, token: str, body: str = ""):
    """Approve a GitHub PR with an optional review comment."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": GITHUB_REST_API_VERSION,
    }
    payload = {
        "event": "APPROVE",
        "body": body,
    }
    r = requests.post(url, headers=headers, json=payload)
    r.raise_for_status()
    return r.json()


def submit_pr_review(
    owner: str,
    repo: str,
    pr_number: int,
    token: str,
    event: str,
    body: str = "",
):
    """Submit a GitHub pull request review event (APPROVE / REQUEST_CHANGES / COMMENT)."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
    r = requests.post(
        url,
        headers=_issue_headers(token),
        json={
            "event": event,
            "body": body,
        },
        timeout=_DEFAULT_REQUEST_TIMEOUT_SEC,
    )
    r.raise_for_status()
    return r.json()


def create_pr_review_comment(
    owner: str,
    repo: str,
    pr_number: int,
    token: str,
    body: str,
    commit_id: str,
    path: str,
    line: int,
    side: str = "RIGHT",
    start_line: int | None = None,
    start_side: str | None = None,
):
    """
    Create an inline review comment on a specific line or range of lines in a PR.

    Parameters
    ----------
    owner : str
        Repository owner
    repo : str
        Repository name
    pr_number : int
        Pull request number
    token : str
        GitHub access token
    body : str
        The comment text
    commit_id : str
        SHA of the commit being commented on (use HEAD SHA of the PR)
    path : str
        Relative path to the file in the repository
    line : int
        The line number where the comment applies (for multi-line, this is the last line)
    side : str
        Which side of the diff: "LEFT" (deletions/old) or "RIGHT" (additions/new). Default: "RIGHT"
    start_line : int, optional
        Starting line for multi-line comments
    start_side : str, optional
        Starting side for multi-line comments ("LEFT" or "RIGHT")

    Returns
    -------
    dict
        GitHub API response with the created comment

    Examples
    --------
    Single-line comment:
        create_pr_review_comment(
            "owner", "repo", 123, token, "Fix this typo",
            "abc123", "src/file.ts", 45
        )

    Multi-line comment:
        create_pr_review_comment(
            "owner", "repo", 123, token, "Refactor this block",
            "abc123", "src/file.ts", 50,
            start_line=45, start_side="RIGHT"
        )
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": GITHUB_REST_API_VERSION,
    }

    payload = {
        "body": body,
        "commit_id": commit_id,
        "path": path,
        "line": line,
        "side": side,
    }

    if start_line is not None:
        payload["start_line"] = start_line
    if start_side is not None:
        payload["start_side"] = start_side

    r = requests.post(url, headers=headers, json=payload)
    r.raise_for_status()
    return r.json()
