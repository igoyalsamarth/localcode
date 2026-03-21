"""GitHub REST API helpers for issues (reactions, comments, labels)."""

from urllib.parse import quote

import requests

from constants import GITHUB_REST_API_VERSION


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

    print(f"Adding reaction '{reaction}' to issue #{issue_number} in {owner}/{repo}...")
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
