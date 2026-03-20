"""
Deep-agent GitHub coder: clones repos, implements issues, opens PRs.

Invoked via `run_agent_on_issue` (e.g. from `services.github.coder_workflow`).
Uses LangGraph checkpointing (PostgreSQL via ``db.client.get_psycopg_conninfo()``) with a
stable ``thread_id`` per issue (see LangGraph persistence / threads docs).
"""

import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_ollama import ChatOllama

from agents.checkpoint import coder_thread_id, get_checkpointer
from agents.usage_callback import CoderLlmUsageCallbackHandler
from constants import CODER_LLM_PROVIDER, get_coder_model_name
from services.github.coder_usage import record_coder_workflow_usage
from services.github.issue_payload import IssueOpenedForCoder

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
    model=get_coder_model_name(),
    max_retries=10,
    timeout=120,
)

_agent = None


def get_github_coder_agent():
    """Lazy init so ``constants`` / ``DATABASE_URL`` are loaded before the graph is built."""
    global _agent
    if _agent is None:
        _agent = create_deep_agent(
            model=llm,
            system_prompt=instructions,
            backend=backend,
            checkpointer=get_checkpointer(),
        )
    return _agent


def run_agent_on_issue(issue: IssueOpenedForCoder) -> None:
    """
    Run the GitHub coder agent for a triggered issue (queue label already moved to
    ``greagent:in-progress`` by the webhook). Clones the repo, implements, opens a PR,
    and comments; the HTTP layer sets ``greagent:done`` or ``greagent:error`` afterward.

    Checkpoints are keyed by ``thread_id`` = ``github:{owner}/{repo}#issue-{n}`` so the
    same issue run can be resumed or replayed from stored LangGraph state.
    """
    full_name = issue.full_name
    clone_url = f"https://x-access-token:$GITHUB_TOKEN@github.com/{full_name}.git"
    prompt = f"""In the repository {issue.repo_url} (repo folder: repos/{issue.repo_name}):

**Issue #{issue.issue_number}: {issue.issue_title}**

{issue.issue_body or "(No description provided)"}

Please implement the requested changes:
1. Clone the repo to repos/{issue.repo_name} if it doesn't exist (use: git clone {clone_url} repos/{issue.repo_name})
2. Create a new branch named exactly: agent/issue-{issue.issue_number}
3. Make the required code changes
4. Commit your changes (remember 🤖 in commit message)
5. Before pushing, ensure the remote uses GITHUB_TOKEN: git remote set-url origin {clone_url}
6. Push the branch: git push origin agent/issue-{issue.issue_number}
7. Raise a PR against the default branch with a relevant title and body (gh pr create [flags]), remember to mention in the body that this PR "Closes #{issue.issue_number}" so that the issue gets auto-closed when the PR is merged.
8. Comment on the pull request with a short summary and a link to the issue.
9. Comment on the issue that the PR was opened and include the PR link.

"""
    thread_id = coder_thread_id(issue.full_name, issue.issue_number)
    usage_cb = CoderLlmUsageCallbackHandler()
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [usage_cb],
    }

    agent = get_github_coder_agent()
    try:
        for chunk in agent.stream(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ]
            },
            config,
            stream_mode="messages",
            subgraphs=True,
            version="v2",
        ):
            if chunk["type"] == "messages":
                token, metadata = chunk["data"]

                # Identify source: "main" or the subagent namespace segment
                is_subagent = any(s.startswith("tools:") for s in chunk["ns"])
                source = (
                    next((s for s in chunk["ns"] if s.startswith("tools:")), "main")
                    if is_subagent
                    else "main"
                )

                # Tool call chunks (streaming tool invocations)
                tool_call_chunks = getattr(token, "tool_call_chunks", None) or []
                if tool_call_chunks:
                    for tc in tool_call_chunks:
                        if tc.get("name"):
                            print(f"[{source}] Tool call: {tc['name']}")
                        # Args stream in chunks - write them incrementally
                        if tc.get("args"):
                            print(tc["args"], end="", flush=True)

                # Tool results
                if token.type == "tool":
                    print(
                        f"[{source}] Tool result [{token.name}]: {str(token.content)[:150]}"
                    )

                # Regular AI content (skip tool call messages)
                if token.type == "ai" and token.content and not tool_call_chunks:
                    print(token.content, end="", flush=True)

            print()
    finally:
        record_coder_workflow_usage(
            issue,
            thread_id,
            usage_cb,
            provider=CODER_LLM_PROVIDER,
            fallback_model_name=get_coder_model_name(),
        )
