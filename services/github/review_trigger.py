"""
Map GitHub ``pull_request`` webhook payloads to review work items using DB state.

- ``mode: auto`` (default): trigger on ``opened`` / ``synchronize`` (new commits).
- Applying ``greagent:review`` (``labeled``) always starts a run when the agent is enabled,
  including in auto mode (explicit rerun).
- ``mode: tag``: trigger only when ``greagent:review`` is applied — no auto run on open/sync.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from model.enums import AgentType
from model.tables import Agent, Repository, RepositoryAgent
from services.github.greagent_labels import REVIEW as REVIEW_LABEL_QUEUE
from services.github.pr_payload import PROpenedForReview
from services.github.trigger_modes import TRIGGER_MODE_AUTO


def resolve_review_pr_work(
    session: Session, data: dict[str, Any]
) -> PROpenedForReview | None:
    """
    Return a work item when this webhook should start the reviewer, else ``None``.

    Respects ``RepositoryAgent.enabled`` and ``config_json.mode``.
    Default mode matches bootstrap: ``auto`` (review on every new/updated PR).
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

    raw_mode = (ra.config_json or {}).get("mode", TRIGGER_MODE_AUTO)
    is_auto = str(raw_mode).lower() == TRIGGER_MODE_AUTO

    if action in ("opened", "synchronize"):
        if not is_auto:
            return None
        return PROpenedForReview.from_github_pr_event(data)

    if action == "labeled":
        label_name = (data.get("label") or {}).get("name")
        if not isinstance(label_name, str) or label_name.strip() != REVIEW_LABEL_QUEUE:
            return None
        return PROpenedForReview.from_github_pr_event(data)

    return None
