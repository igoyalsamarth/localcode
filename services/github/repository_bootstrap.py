"""
Create or update ``Repository`` rows from GitHub payloads and ensure default coder config.

Default: coder agent enabled with ``mode: auto`` when a repository is first linked.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from model.enums import AgentType
from model.tables import Agent, Model, Repository, RepositoryAgent

CODER_MODE_AUTO = "auto"


def get_or_create_default_model(session: Session) -> Model:
    m = session.execute(select(Model).limit(1)).scalar_one_or_none()
    if not m:
        m = Model(provider="openai", name="gpt-4")
        session.add(m)
        session.flush()
    return m


def get_or_create_coder_agent(session: Session, organization_id: UUID) -> Agent:
    stmt = select(Agent).where(
        Agent.organization_id == organization_id,
        Agent.type == AgentType.code,
    )
    agent = session.execute(stmt).scalar_one_or_none()
    if not agent:
        agent = Agent(
            organization_id=organization_id,
            name="Code Agent",
            type=AgentType.code,
        )
        session.add(agent)
        session.flush()
    return agent


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


def ensure_default_coder_repository_agent(session: Session, repository: Repository) -> None:
    """
    If there is no ``RepositoryAgent`` row for the org's code agent, create one:
    ``enabled=True``, ``config_json`` ``{\"mode\": \"auto\"}``.
    """
    agent = get_or_create_coder_agent(session, repository.organization_id)
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
            config_json={"mode": CODER_MODE_AUTO},
        )
    )
