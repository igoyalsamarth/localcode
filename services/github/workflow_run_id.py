"""Stable workflow keys for GitHub code/review runs (usage rows, stream config, sandboxes).

The :class:`~model.tables.AgentWorkflowUsage` primary key ``id`` is unique per execution;
``run_id`` is the same string for every run of a given issue or PR so aggregates and
tracing line up with the GitHub workflow, not a one-off UUID.
"""


def github_issue_workflow_run_id(full_name: str, issue_number: int) -> str:
    """``github:{owner}/{repo}#issue-{n}`` for issue coding."""
    return f"github:{full_name}#issue-{issue_number}"


def github_pr_workflow_run_id(full_name: str, pr_number: int) -> str:
    """``github:{owner}/{repo}#pr-{n}`` for PR review."""
    return f"github:{full_name}#pr-{pr_number}"
