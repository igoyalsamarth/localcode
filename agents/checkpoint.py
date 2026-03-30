"""
Stable workflow identifiers for GitHub deep-agent runs.

These strings are stored on usage rows (``workflow_thread_id``) and passed as
``config["configurable"]["thread_id"]`` when streaming the agent.
"""


def github_issue_workflow_thread_id(full_name: str, issue_number: int) -> str:
    """Stable id for issue-coding runs (``owner/repo#issue-{n}`` style)."""
    return f"github:{full_name}#issue-{issue_number}"


def github_pr_workflow_thread_id(full_name: str, pr_number: int) -> str:
    """Stable id for PR review runs."""
    return f"github:{full_name}#pr-{pr_number}"
