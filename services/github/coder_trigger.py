"""
Map GitHub ``issues`` webhook payloads to coder work items using DB state.

- ``mode: auto`` (default): trigger on ``opened`` / ``reopened``.
- Applying ``greagent:code`` (``labeled``) always starts a run when the agent is enabled,
  including in auto mode (explicit rerun).
- Any other ``mode`` (e.g. ``on_assignment`` / ``tag``): trigger only when ``greagent:code``
  is applied — no auto run on open/reopen.

Pull requests: the coder runs **only** when ``pull_request`` ``labeled`` adds ``greagent:code``
(same label as issue queue; see :func:`resolve_coder_pr_work`). There is no auto run on PR open/sync.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from model.enums import AgentType
from model.tables import Agent, Repository, RepositoryAgent
from services.github.greagent_labels import CODE as CODE_LABEL_QUEUE
from services.github.issue_payload import IssueOpenedForCoder
from services.github.pr_payload import PROpenedForReview
from services.github.repository_bootstrap import ensure_default_coder_repository_agent
from services.github.trigger_modes import TRIGGER_MODE_AUTO


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

    raw_mode = (ra.config_json or {}).get("mode", TRIGGER_MODE_AUTO)
    is_auto = str(raw_mode).lower() == TRIGGER_MODE_AUTO

    if action in ("opened", "reopened"):
        if not is_auto:
            return None
        return IssueOpenedForCoder.from_github_issues_event(data)

    if action == "labeled":
        label_name = (data.get("label") or {}).get("name")
        if (
            not isinstance(label_name, str)
            or label_name.strip() != CODE_LABEL_QUEUE
        ):
            return None
        return IssueOpenedForCoder.from_github_issues_event(data)

    return None


def resolve_coder_pr_work(
    session: Session, data: dict[str, Any]
) -> PROpenedForReview | None:
    """
    Return PR work when this ``pull_request`` webhook should start the **coder** agent.

    Trigger is **only** ``action == "labeled"`` with label ``greagent:code`` (no auto run
    on ``opened`` / ``synchronize``). Requires the repository's code agent enabled.
    """
    if data.get("action") != "labeled":
        return None

    label_name = (data.get("label") or {}).get("name")
    if (
        not isinstance(label_name, str)
        or label_name.strip() != CODE_LABEL_QUEUE
    ):
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

    return PROpenedForReview.from_github_pr_event(data)
