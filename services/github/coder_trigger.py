"""
Map GitHub ``issues`` webhook payloads to coder work items using DB state.

- ``mode: auto`` (default): trigger on ``opened`` / ``reopened``.
- Any other ``mode`` (e.g. ``label``): trigger only when ``greagent:code`` is applied
  (``labeled``).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from model.enums import AgentType
from model.tables import Agent, Repository, RepositoryAgent
from services.github.coder_labels import CODE as CODER_LABEL_QUEUE
from services.github.issue_payload import IssueOpenedForCoder
from services.github.repository_bootstrap import (
    CODER_MODE_AUTO,
    ensure_default_coder_repository_agent,
)


def resolve_coder_issue_work(
    session: Session, data: dict[str, Any]
) -> IssueOpenedForCoder | None:
    """
    Return a work item when this webhook should start the coder, else ``None``.

    Respects ``RepositoryAgent.enabled`` and ``config_json.mode``.
    """
    action = data.get("action")
    if action not in ("opened", "reopened", "labeled"):
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
            Agent.type == AgentType.code,
        )
    )
    ra = session.execute(stmt).scalar_one_or_none()
    if not ra:
        ensure_default_coder_repository_agent(session, repo_row)
        session.flush()
        ra = session.execute(stmt).scalar_one_or_none()

    if not ra or not ra.enabled:
        return None

    raw_mode = (ra.config_json or {}).get("mode", CODER_MODE_AUTO)
    is_auto = str(raw_mode).lower() == CODER_MODE_AUTO

    if action in ("opened", "reopened"):
        if not is_auto:
            return None
        return IssueOpenedForCoder.from_github_issues_event(data)

    if action == "labeled":
        label_name = (data.get("label") or {}).get("name")
        if (
            not isinstance(label_name, str)
            or label_name.strip() != CODER_LABEL_QUEUE
        ):
            return None
        if is_auto:
            return None
        return IssueOpenedForCoder.from_github_issues_event(data)

    return None
