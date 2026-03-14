import requests


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
    }

    payload = {"content": reaction}

    print(f"Adding reaction '{reaction}' to issue #{issue_number} in {owner}/{repo}...")
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()

    return response.json()


def comment_on_issue(owner: str, repo: str, issue_number: int, token: str, body: str):
    """
    Add a comment to a GitHub issue.
    """

    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }

    payload = {"body": body}

    r = requests.post(url, headers=headers, json=payload)
    r.raise_for_status()
    return r.json()
