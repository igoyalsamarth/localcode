import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_ollama import ChatOllama

instructions = """You are a NodeJS expert who knows how to code in TypeScript and all the CLI commands around it.

Your job is to deliver whatever the user asks for.

Folder Structure:
/
|-repos
  |-example-repo-1
  |-example-repo-2
You operate inside a workspace where the root "/" contains a dirctory "repos" and all repositories are inside this.

## Workspace Rules

- The workspace root "/" is read-only.
- All repositories must live inside "repos" directory.
- When cloning a repo named "example", clone to "repos/example".

Correct example:
git clone https://github.com/user/example repos/example
cd repos/example && git pull

Incorrect:
git clone https://github.com/user/example
cd / && git clone ...

Shell commands must use paths relative to the current directory.

Do NOT use absolute paths such as:
/repos/...

Instead use:

repos/<repo>

Correct: 
cd repo/example

Incorect:
cd /repo/example

Remember to add a robo emoji 🤖 in every commit message of yours in the starting.

Check if the repo exists before cloning, if it does not, then you are free to clone.
"""

Path("workspace/repos").mkdir(parents=True, exist_ok=True)

backend = LocalShellBackend(
    root_dir="./workspace",
    virtual_mode=True,
    inherit_env=True,
)

llm = ChatOllama(
    model=os.environ.get("MODEL", "kimi-k2.5:cloud"),
    max_retries=10,
    timeout=120,
)

agent = create_deep_agent(
    model=llm,
    system_prompt=instructions,
    backend=backend,
)


def run_agent_on_issue(
    repo_url: str,
    repo_name: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
) -> None:
    """
    Run the agent on an issue. The agent will clone the repo, implement changes,
    create branch agent/issue-{N}, commit, and push. PR creation and issue comment
    are done separately by the webhook handler.
    """
    # Extract owner/repo from URL (e.g. https://github.com/owner/repo -> owner/repo)
    full_name = "/".join(repo_url.rstrip("/").rsplit("/", 2)[-2:])
    clone_url = f"https://x-access-token:$GITHUB_TOKEN@github.com/{full_name}.git"
    prompt = f"""In the repository {repo_url} (repo folder: repos/{repo_name}):

**Issue #{issue_number}: {issue_title}**

{issue_body or "(No description provided)"}

Please implement the requested changes:
1. Clone the repo to repos/{repo_name} if it doesn't exist (use: git clone {clone_url} repos/{repo_name})
2. Create a new branch named exactly: agent/issue-{issue_number}
3. Make the required code changes
4. Commit your changes (remember 🤖 in commit message)
5. Push the branch: git push origin agent/issue-{issue_number}

Do NOT create the pull request - that will be done automatically. Just clone, branch, implement, commit, and push."""

    agent.invoke(
        {"messages": [{"role": "user", "content": prompt}]},
        config={"configurable": {}},
    )


if __name__ == "__main__":
    for chunk in agent.stream(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "In the repo https://github.com/igoyalsamarth/localcode-test the PR raised for add-health-check-tests has some merge conflicts, could you resolve them and merge the PR?",
                }
            ]
        },
        stream_mode="updates",
        subgraphs=True,
        version="v2",
    ):
        print(chunk)
