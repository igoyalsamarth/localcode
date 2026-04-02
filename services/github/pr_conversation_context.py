"""
Build LLM-readable context from GitHub PR conversation and inline review comments.
"""

from __future__ import annotations

from typing import Any

from logger import get_logger
from services.github.client import list_pr_issue_comments, list_pr_review_comments

logger = get_logger(__name__)


def _login(user: dict[str, Any] | None) -> str:
    if not user:
        return "unknown"
    login = user.get("login")
    return str(login) if isinstance(login, str) and login else "unknown"


def _line_for_review_comment(c: dict[str, Any]) -> str:
    line = c.get("line")
    if line is not None:
        return str(line)
    orig = c.get("original_line")
    if orig is not None:
        return str(orig)
    return "?"


_CONV_HEADER = "### Conversation comments (timeline)\n"
_CONV_TRUNC_LEAD = (
    "[Older conversation comments were omitted due to size limits; "
    "below is the most recent portion of the thread.]\n\n"
)


def _format_conversation_section(conv_blocks: list[str], max_chars: int) -> str:
    """
    Build the timeline section. When over ``max_chars``, keep **newest** comments
    (GitHub returns issue comments oldest-first; we drop from the start).
    """
    if not conv_blocks:
        return ""
    header = _CONV_HEADER
    body = "\n".join(conv_blocks)
    full = header + body
    if len(full) <= max_chars:
        return full

    notice = _CONV_TRUNC_LEAD
    budget = max_chars - len(header) - len(notice)
    if budget < 40:
        return (header + notice.rstrip()).strip() + "\n"

    kept: list[str] = []
    used = 0
    for block in reversed(conv_blocks):
        sep_len = 1 if kept else 0
        if used + sep_len + len(block) <= budget:
            kept.insert(0, block)
            used += sep_len + len(block)
        elif not kept:
            # Newest comment alone exceeds budget — keep its trailing characters only.
            kept = [block[-budget:].lstrip()]
            break
        else:
            break

    return header + notice + "\n".join(kept)


def format_pr_comments_for_llm(
    issue_comments: list[dict[str, Any]],
    review_comments: list[dict[str, Any]],
    *,
    max_chars: int = 24_000,
) -> str:
    """
    Turn GitHub API comment payloads into a single markdown-ish block for the agent prompt.

    ``max_chars`` applies **only** to the conversation (issue timeline) section.
    When the timeline is too long, **older** comments are dropped first so the **latest**
    thread remains visible. Inline review comments (including full ``diff_hunk`` text) are
    never truncated.
    """
    parts: list[str] = []

    conv_blocks: list[str] = []
    for c in issue_comments:
        author = _login(c.get("user") if isinstance(c.get("user"), dict) else None)
        created = c.get("created_at") or ""
        body = c.get("body")
        text = body.strip() if isinstance(body, str) else ""
        if not text:
            continue
        conv_blocks.append(f"- **@{author}** ({created})\n\n{text}\n")
    if conv_blocks:
        parts.append(_format_conversation_section(conv_blocks, max_chars))

    review_blocks: list[str] = []
    sorted_rc = sorted(
        review_comments,
        key=lambda x: (
            str(x.get("path") or ""),
            int(x.get("line") or x.get("original_line") or 0),
        ),
    )
    for c in sorted_rc:
        author = _login(c.get("user") if isinstance(c.get("user"), dict) else None)
        created = c.get("created_at") or ""
        path = c.get("path")
        path_s = str(path) if isinstance(path, str) else "?"
        line_s = _line_for_review_comment(c)
        body = c.get("body")
        text = body.strip() if isinstance(body, str) else ""
        if not text:
            continue
        block = f"- **@{author}** on `{path_s}` line {line_s} ({created})\n\n{text}\n"
        dh = c.get("diff_hunk")
        if isinstance(dh, str) and dh.strip():
            block += (
                f"\n  _Diff hunk:_\n  ```diff\n{dh.strip()}\n  ```\n"
            )
        review_blocks.append(block)
    if review_blocks:
        parts.append("\n### Inline review comments (on the diff)\n" + "\n".join(review_blocks))

    raw = "\n".join(parts).strip()
    return raw


def fetch_pr_conversation_context_for_llm(
    owner: str,
    repo: str,
    pr_number: int,
    token: str,
    *,
    max_chars: int = 24_000,
) -> str:
    """
    Fetch issue comments and pull review comments, then format for the LLM.

    ``max_chars`` limits only the timeline (issue) comments (oldest dropped first when
    trimming); review comments are not cut.

    On failure, logs and returns an empty string so the agent run can continue.
    """
    try:
        issue_comments = list_pr_issue_comments(owner, repo, pr_number, token)
        review_comments = list_pr_review_comments(owner, repo, pr_number, token)
    except Exception:
        logger.exception(
            "Failed to fetch PR comments for LLM context %s/%s#%s",
            owner,
            repo,
            pr_number,
        )
        return ""

    return format_pr_comments_for_llm(
        issue_comments,
        review_comments,
        max_chars=max_chars,
    )
