"""
Create or update ``Repository`` rows from GitHub payloads and ensure default agent links.

Bootstraps ``RepositoryAgent`` rows for issue (``code``) and PR (``review``) workflows when
a repository is first linked.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from constants import default_catalog_model_spec
from model.enums import AgentType
from model.tables import Agent, Model, Repository, RepositoryAgent
from services.github.trigger_modes import TRIGGER_MODE_AUTO

_AGENT_DEFAULT_DISPLAY_NAMES: dict[AgentType, str] = {
    AgentType.code: "Code Agent",
    AgentType.review: "Review Agent",
}


def get_or_create_default_model(session: Session) -> Model:
    """
    Return the catalog row for :func:`~constants.default_catalog_model_spec`, creating it if missing.

    Matches on ``(provider, name)`` from env (``AGENT_LLM_PROVIDER``, ``MODEL``), not ``LIMIT 1``,
    so another catalog row existing does not block the default Kimi (or configured) model row.
    """
    provider, name, inp, out = default_catalog_model_spec()
    stmt = select(Model).where(Model.provider == provider, Model.name == name)
    m = session.execute(stmt).scalar_one_or_none()
    if not m:
        m = Model(
            provider=provider,
            name=name,
            input_cost_per_token=inp,
            output_cost_per_token=out,
        )
        session.add(m)
        session.flush()
    return m


def get_or_create_agent(
    session: Session, organization_id: UUID, agent_type: AgentType
) -> Agent:
    """Return the org's agent row for ``agent_type``, creating it with a default name if missing."""
    stmt = select(Agent).where(
        Agent.organization_id == organization_id,
        Agent.type == agent_type,
    )
    agent = session.execute(stmt).scalar_one_or_none()
    if not agent:
        default_name = _AGENT_DEFAULT_DISPLAY_NAMES.get(
            agent_type,
            f"{agent_type.value.title()} Agent",
        )
        agent = Agent(
            organization_id=organization_id,
            name=default_name,
            type=agent_type,
        )
        session.add(agent)
        session.flush()
    return agent


def get_or_create_coder_agent(session: Session, organization_id: UUID) -> Agent:
    return get_or_create_agent(session, organization_id, AgentType.code)


def get_or_create_review_agent(session: Session, organization_id: UUID) -> Agent:
    return get_or_create_agent(session, organization_id, AgentType.review)


def upsert_repository_from_github(
    session: Session,
    organization_id: UUID,
    repo: dict[str, Any],
    *,
    account_login_fallback: str | None = None,
) -> Repository:
    """Insert or update a ``Repository`` from a GitHub ``repository`` object."""
    repo_id = repo.get("id")
    if repo_id is None:
        raise ValueError("GitHub repository payload missing id")

    name = repo.get("name")
    if not name:
        raise ValueError("GitHub repository payload missing name")

    full_name = repo.get("full_name") or ""
    if "/" in full_name:
        owner = full_name.split("/", 1)[0]
    else:
        owner = account_login_fallback or ""

    stmt = select(Repository).where(
        Repository.organization_id == organization_id,
        Repository.github_repo_id == int(repo_id),
    )
    row = session.execute(stmt).scalar_one_or_none()

    private = bool(repo.get("private", False))
    branch = repo.get("default_branch") or "main"

    if row:
        row.name = str(name)
        row.owner = owner or row.owner
        row.private = private
        row.default_branch = branch
        return row

    new_repo = Repository(
        organization_id=organization_id,
        github_repo_id=int(repo_id),
        name=str(name),
        owner=owner,
        private=private,
        default_branch=branch,
        active=True,
    )
    session.add(new_repo)
    session.flush()
    return new_repo


def _ensure_repository_agent_link(
    session: Session,
    repository: Repository,
    *,
    agent_type: AgentType,
    default_mode: str,
) -> None:
    agent = get_or_create_agent(session, repository.organization_id, agent_type)
    stmt = select(RepositoryAgent).where(
        RepositoryAgent.repository_id == repository.id,
        RepositoryAgent.agent_id == agent.id,
    )
    if session.execute(stmt).scalar_one_or_none():
        return

    model = get_or_create_default_model(session)
    session.add(
        RepositoryAgent(
            repository_id=repository.id,
            agent_id=agent.id,
            model_id=model.id,
            enabled=True,
            config_json={"mode": default_mode},
        )
    )


def ensure_default_coder_repository_agent(
    session: Session, repository: Repository
) -> None:
    """
    If there is no ``RepositoryAgent`` row for the org's code agent, create one:
    ``enabled=True``, ``config_json`` ``{\"mode\": \"auto\"}`` (``TRIGGER_MODE_AUTO``).
    """
    _ensure_repository_agent_link(
        session,
        repository,
        agent_type=AgentType.code,
        default_mode=TRIGGER_MODE_AUTO,
    )


def ensure_default_review_repository_agent(
    session: Session, repository: Repository
) -> None:
    """
    If there is no ``RepositoryAgent`` row for the org's review agent, create one:
    ``enabled=True``, ``config_json`` ``{\"mode\": \"auto\"}`` (``TRIGGER_MODE_AUTO``),
    same as the code agent — new PRs are reviewed automatically; ``greagent:review``
    still triggers (or retriggers) a run when applied.
    """
    _ensure_repository_agent_link(
        session,
        repository,
        agent_type=AgentType.review,
        default_mode=TRIGGER_MODE_AUTO,
    )
