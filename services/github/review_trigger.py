"""
Map GitHub ``pull_request`` webhook payloads to review work items using DB state.

- ``mode: tag`` (default for review agent): trigger only when ``greagent:review`` is applied (``labeled``).
- ``mode: auto``: trigger on ``opened`` / ``synchronize`` (new commits).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from model.enums import AgentType
from model.tables import Agent, Repository, RepositoryAgent
from services.github.coder_labels import REVIEW as REVIEW_LABEL_QUEUE
from services.github.pr_payload import PROpenedForReview

REVIEW_MODE_TAG = "tag"
REVIEW_MODE_AUTO = "auto"


def resolve_review_pr_work(
    session: Session, data: dict[str, Any]
) -> PROpenedForReview | None:
    """
    Return a work item when this webhook should start the reviewer, else ``None``.

    Respects ``RepositoryAgent.enabled`` and ``config_json.mode``.
    Default mode for review agent is ``tag`` (unlike coder which defaults to ``auto``).
    """
    action = data.get("action")
    if action not in ("opened", "synchronize", "labeled"):
        return None

    repo_payload = data.get("repository") or {}
    gh_repo_id = repo_payload.get("id")
    if gh_repo_id is None:
        return None

    stmt = select(Repository).where(Repository.github_repo_id == int(gh_repo_id))
    repo_row = session.execute(stmt).scalar_one_or_none()
    if not repo_row:
        return None

    stmt = (
        select(RepositoryAgent)
        .join(Agent, RepositoryAgent.agent_id == Agent.id)
        .where(
            RepositoryAgent.repository_id == repo_row.id,
            Agent.type == AgentType.review,
        )
    )
    ra = session.execute(stmt).scalar_one_or_none()

    if not ra or not ra.enabled:
        return None

    raw_mode = (ra.config_json or {}).get("mode", REVIEW_MODE_TAG)
    is_auto = str(raw_mode).lower() == REVIEW_MODE_AUTO

    if action in ("opened", "synchronize"):
        if not is_auto:
            return None
        return PROpenedForReview.from_github_pr_event(data)

    if action == "labeled":
        label_name = (data.get("label") or {}).get("name")
        if (
            not isinstance(label_name, str)
            or label_name.strip() != REVIEW_LABEL_QUEUE
        ):
            return None
        if is_auto:
            return None
        return PROpenedForReview.from_github_pr_event(data)

    return None
