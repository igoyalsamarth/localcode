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
