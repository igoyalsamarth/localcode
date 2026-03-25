"""
LangChain tools for the GitHub reviewer agent.

These tools allow the agent to create inline review comments on specific lines of code.
"""

from __future__ import annotations

import os
from typing import Optional

from langchain_core.tools import tool

from services.github.client import create_pr_review_comment


@tool
def add_inline_review_comment(
    path: str,
    line: int,
    body: str,
    start_line: Optional[int] = None,
    side: str = "RIGHT",
    start_side: Optional[str] = None,
) -> str:
    """
    Add an inline review comment to a specific line or range of lines in the pull request.

    Use this tool to comment on specific code changes with suggestions, nitpicks, or issues.
    This creates the inline comments you see in GitHub PR reviews where you can select
    code and add targeted feedback.

    Args:
        path: Relative path to the file (e.g., "src/components/Button.tsx")
        line: The line number to comment on (for multi-line, this is the LAST line)
        body: Your comment text (supports markdown)
        start_line: Optional starting line for multi-line comments (must be < line)
        side: Which side of diff - "RIGHT" for new code (default), "LEFT" for deleted code
        start_side: Starting side for multi-line comments (usually same as side)

    Returns:
        Success message with the comment URL

    Examples:
        Single-line comment:
            add_inline_review_comment(
                path="src/utils.ts",
                line=42,
                body="Consider using `const` instead of `let` here."
            )

        Multi-line comment (lines 10-15):
            add_inline_review_comment(
                path="src/api.ts",
                line=15,
                start_line=10,
                body="This entire block could be simplified using async/await."
            )

        Comment on deleted code:
            add_inline_review_comment(
                path="src/old.ts",
                line=20,
                side="LEFT",
                body="Good catch removing this deprecated function!"
            )
    """
    # Get PR context from environment variables set by the reviewer
    owner = os.environ.get("REVIEW_OWNER")
    repo = os.environ.get("REVIEW_REPO")
    pr_number = os.environ.get("REVIEW_PR_NUMBER")
    commit_id = os.environ.get("REVIEW_HEAD_SHA")
    token = os.environ.get("GH_TOKEN")

    if not all([owner, repo, pr_number, commit_id, token]):
        missing = []
        if not owner:
            missing.append("REVIEW_OWNER")
        if not repo:
            missing.append("REVIEW_REPO")
        if not pr_number:
            missing.append("REVIEW_PR_NUMBER")
        if not commit_id:
            missing.append("REVIEW_HEAD_SHA")
        if not token:
            missing.append("GH_TOKEN")
        return f"Error: Missing required environment variables: {', '.join(missing)}"

    try:
        result = create_pr_review_comment(
            owner=owner,
            repo=repo,
            pr_number=int(pr_number),
            token=token,
            body=body,
            commit_id=commit_id,
            path=path,
            line=line,
            side=side,
            start_line=start_line,
            start_side=start_side,
        )
        comment_url = result.get("html_url", "")
        return f"✓ Review comment added to {path}:{line}\nURL: {comment_url}"
    except Exception as e:
        return f"Error creating review comment: {str(e)}"
